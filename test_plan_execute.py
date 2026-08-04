"""
Plan-and-Execute 路径端到端测试脚本

用法: python test_plan_execute.py

验证内容（针对工具注入修复后的回归测试）：
1. 查询分类器将测试问题判为 complex（才会走 Plan-Execute 路径）
2. Plan 阶段：plan_model 生成执行计划（plan_start / plan_step 事件）
3. 执行阶段：每个步骤的工具组正确注入（tool_start / tool_end 事件，
   这是本次修复的核心验证点——之前步骤只能拿到 base 组）
4. 综合阶段：synthesize 汇总结果并输出 plan_complete

说明：
- 使用真实模型（DashScope）和真实数据库（MySQL）
- 自动创建临时测试用户（test_plan_execute_xxx），结束后清理其数据，
  不污染真实账号
- 若想保留测试产生的笔记，可设置 KEEP_DATA=1
"""

import asyncio
import sys
import time
import uuid as uuid_mod
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Windows 控制台 UTF-8 输出
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

KEEP_DATA = sys.argv[1] == "1" if len(sys.argv) > 1 else False

from sqlalchemy import text

from app.db.database import async_session_factory

# 测试问题：包含 搜索/统计/创建/回顾 四个工具意图 → L1 规则判定为 complex
TEST_QUESTION = (
    "请帮我做一个学习整理任务：先搜索我笔记中关于 Python 的所有内容，"
    "然后统计我的笔记分类分布，再创建一篇学习总结笔记，"
    "最后回顾一下我今天需要复习的内容。"
)


async def create_test_user() -> str:
    """创建临时测试用户，返回 uuid"""
    from app.utils.auth_utils import pwd_context

    test_username = f"test_plan_execute_{datetime.now().strftime('%H%M%S')}"
    test_uuid = str(uuid_mod.uuid4())
    async with async_session_factory() as db:
        await db.execute(
            text(
                "INSERT INTO users (uuid, username, password, status) "
                "VALUES (:uuid, :username, :password, 'active')"
            ),
            {
                "uuid": test_uuid,
                "username": test_username,
                "password": pwd_context.hash("Test@12345"),
            },
        )
        await db.commit()
    return test_uuid


async def cleanup_test_user(user_id: str):
    """清理测试用户数据（回顾记录 → 笔记 → 用户）"""
    try:
        async with async_session_factory() as db:
            await db.execute(
                text("DELETE FROM review_records WHERE user_id = :uid"), {"uid": user_id}
            )
            await db.execute(
                text("DELETE FROM notes WHERE user_id = :uid"), {"uid": user_id}
            )
            await db.execute(
                text("DELETE FROM users WHERE uuid = :uid"), {"uid": user_id}
            )
            await db.commit()
        print(f"[清理] 已删除测试用户数据: {user_id}")
    except Exception as e:
        print(f"[清理] 失败（请手动清理）: {e}")


async def main():
    # ===== 1. 初始化模型与服务（与 main.py 的 init_manager 一致） =====
    from app.utils.factory import (
        create_chat_model, create_plan_model, create_embed_model,
    )
    from app.rag.vector_store import VectorStoreService
    from app.services.note_service import NoteService
    from app.services.review_service import ReviewService

    print("== 初始化模型 ==")
    chat_model = create_chat_model()
    plan_model = create_plan_model()
    embed_model = create_embed_model()

    vector_store = VectorStoreService(embed_model=embed_model)
    note_service = NoteService(vector_store=vector_store, chat_model=chat_model)
    review_service = ReviewService()

    # ===== 2. 创建临时测试用户 =====
    user_id = await create_test_user()
    print(f"[测试用户] {user_id}")

    try:
        # ===== 3. 复杂度分类（应判为 complex） =====
        from app.ai_service.query_classifier import QueryClassifier

        classifier = QueryClassifier(llm_model=None)  # 仅用 L1 规则
        result = await classifier.classify(TEST_QUESTION)
        print(
            f"[分类] complexity={result.complexity}, source={result.source}, "
            f"reason={result.reason}"
        )
        if result.complexity != "complex":
            print("✗ 测试问题未被判为 complex，无法走到 Plan-Execute 路径，测试中止")
            return

        # ===== 4. 执行 Plan-and-Execute =====
        from app.ai_service.plan_execute_agent import execute_plan_agent
        from app.utils.prompt_loader import load_prompt

        system_prompt = load_prompt("main")
        system_prompt = system_prompt.replace(
            "{current_time}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        print("\n========== Plan-and-Execute 开始 ==========")
        t0 = time.monotonic()
        stats = {
            "plan_ok": False,
            "complete_ok": False,
            "tool_calls": [],
            "steps": 0,
            "errors": [],
        }
        # 缓存各阶段响应文本（response 事件是逐 token 的，边界处统一打印）
        buf = {"phase": None, "text": ""}

        def flush_buf():
            if buf["text"]:
                tag = "步骤响应" if buf["phase"] == "step" else "最终回答"
                print(f"\n-------- {tag} --------")
                print(buf["text"].strip()[:600])
            buf["text"] = ""

        async for event in execute_plan_agent(
            chat_model=chat_model,
            plan_model=plan_model,
            user_id=user_id,
            user_message=TEST_QUESTION,
            system_prompt=system_prompt,
            compressed_messages=[],
            db_session_factory=async_session_factory,
            note_service=note_service,
            review_service=review_service,
            timeout=180,
        ):
            et = event.get("type")

            if et == "plan_start":
                stats["plan_ok"] = True
                print(f"\n[Plan 生成] goal={event.get('goal')} | 共 {event.get('total_steps')} 步")
            elif et == "plan_step":
                print(f"  · 步骤{event['step']}: {event.get('action')}  [tool: {event.get('status')}]")
            elif et == "plan_step_start":
                stats["steps"] += 1
                flush_buf()
                buf["phase"] = "step"
                print(f"\n[执行 步骤{event['step']}] {event.get('action')}")
            elif et == "tool_start":
                stats["tool_calls"].append(event.get("name"))
                print(f"  → 调用工具: {event.get('name')}")
            elif et == "tool_end":
                print(f"  ← 工具完成: {event.get('name')} ({event.get('duration_ms')}ms)")
            elif et == "plan_step_end":
                flush_buf()
                buf["phase"] = None
                print(f"[步骤{event['step']} 结束] result={str(event.get('result'))[:120]}")
            elif et == "plan_synthesize":
                flush_buf()
                buf["phase"] = "synthesize"
                print("\n[汇总中...]")
            elif et == "plan_complete":
                stats["complete_ok"] = True
                flush_buf()
                buf["phase"] = None
                print(
                    f"\n[Plan-Execute 完成] total={event['total_steps']}, "
                    f"completed={event['completed_steps']}"
                )
            elif et == "response":
                buf["text"] += event.get("content", "")
            elif et == "plan_fallback":
                print(f"\n[Plan 降级] reason={event.get('reason')}")
            elif et == "error":
                stats["errors"].append(str(event.get("content")))
                print(f"\n[错误] {event.get('content')}")

        elapsed = time.monotonic() - t0

        # ===== 5. 结论 =====
        print("\n========== 测试结论 ==========")
        print(f"Plan 阶段成功:       {'✓' if stats['plan_ok'] else '✗'}")
        print(f"执行步骤数:          {stats['steps']}")
        print(f"实际调用工具:        {stats['tool_calls'] if stats['tool_calls'] else '（无）'}")
        print(f"综合阶段完成:        {'✓' if stats['complete_ok'] else '✗'}")
        print(f"错误事件:            {stats['errors'] if stats['errors'] else '无'}")
        print(f"总耗时:              {elapsed:.1f}s")
        passed = (
            stats["plan_ok"]
            and stats["complete_ok"]
            and len(stats["tool_calls"]) >= 2  # 至少调用 2 个不同工具
            and not stats["errors"]
        )
        print(f"结论: {'✅ Plan-and-Execute 路径运行成功' if passed else '❌ 存在异常，请检查上方输出'}")
    finally:
        if not KEEP_DATA:
            await cleanup_test_user(user_id)
        else:
            print(f"[保留数据] 测试用户未清理: {user_id}")


if __name__ == "__main__":
    asyncio.run(main())
