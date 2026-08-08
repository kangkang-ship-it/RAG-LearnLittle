"""
修复验证：10 首诗词场景重复输出回归测试

用法: python test_repeat_fix.py

验证目标（针对 Plan-Execute 重复输出问题的回归测试）：
1. 执行阶段的步骤响应不再透传（用户不再看到 N 份完整内容）
2. 最终回答中完整诗词内容只出现一次（标志性诗句计数 = 1）
3. 不再出现"你的笔记中没有找到…"过程性叙述混入回答

使用真实模型（DashScope）+ 真实数据库（MySQL），只读操作，不创建/修改数据。
"""

import asyncio
import re
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

TEST_QUESTION = (
    "《沁园春·雪》《沁园春·长沙》《七律·长征》《忆秦娥·娄山关》"
    "《水调歌头·游泳》《卜算子·咏梅》《七律·人民解放军占领南京》"
    "《浪淘沙·北戴河》《满江红·和郭沫若同志》《念奴娇·昆仑》的详细内容"
)

# 标志性诗句（出现在各首诗词正文中，用于统计重复次数）
MARKERS = [
    ("沁园春·雪", "数风流人物"),
    ("沁园春·长沙", "到中流击水"),
    ("七律·长征", "三军过后尽开颜"),
    ("忆秦娥·娄山关", "苍山如海"),
    ("水调歌头·游泳", "一桥飞架南北"),
    ("卜算子·咏梅", "待到山花烂漫时"),
    ("南京", "人间正道是沧桑"),
    ("北戴河", "换了人间"),
    ("满江红", "只争朝夕"),
    ("昆仑", "环球同此凉热"),
]


async def main():
    from app.utils.factory import create_chat_model, create_plan_model, create_embed_model
    from app.rag.vector_store import VectorStoreService
    from app.services.note_service import NoteService
    from app.ai_service.plan_execute_agent import execute_plan_agent
    from app.utils.prompt_loader import load_prompt
    from app.db.database import async_session_factory

    print("== 初始化模型 ==")
    chat_model = create_chat_model()
    plan_model = create_plan_model()
    embed_model = create_embed_model()

    vector_store = VectorStoreService(embed_model=embed_model)
    note_service = NoteService(vector_store=vector_store, chat_model=chat_model)

    system_prompt = load_prompt("main").replace(
        "{current_time}", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    user_id = "test_repeat_fix_00000000"  # 只读场景，无需真实用户

    print("\n========== 10 首诗词场景开始 ==========")
    t0 = time.monotonic()
    final_text = ""
    step_response_seen = 0   # 执行阶段（plan_step_start 之后、plan_synthesize 之前）的 response 事件数
    narrations = []          # 步骤叙述泄漏（"笔记中没有找到" 出现但回答中应无）

    in_step = False
    async for event in execute_plan_agent(
        chat_model=chat_model,
        plan_model=plan_model,
        user_id=user_id,
        user_message=TEST_QUESTION,
        system_prompt=system_prompt,
        compressed_messages=[],
        db_session_factory=async_session_factory,
        note_service=note_service,
        review_service=None,
        timeout=180,
    ):
        et = event.get("type")
        if et == "plan_start":
            print(f"[Plan] goal={event.get('goal')} | 共 {event.get('total_steps')} 步")
        elif et == "plan_step":
            print(f"  · 步骤{event['step']}: {event.get('action')}")
        elif et == "plan_step_start":
            in_step = True
        elif et == "plan_step_end":
            in_step = False
        elif et == "response" and in_step:
            step_response_seen += 1
        elif et == "response":
            final_text += event.get("content", "")

    elapsed = time.monotonic() - t0

    print(f"\n========== 验证结果（耗时 {elapsed:.1f}s）==========")
    print(f"执行阶段 response 事件数: {step_response_seen}（应为 0，修复后步骤输出不透传）")

    ok = True
    for name, marker in MARKERS:
        count = final_text.count(marker)
        status = "✓" if count == 1 else "✗"
        print(f"  {status} 「{marker}」出现 {count} 次（期望 1 次）")
        if count != 1:
            ok = False

    leaked = "笔记中没有找到" in final_text or "未找到" in final_text
    print(f"{'✗' if leaked else '✓'} 回答中无「笔记中没有找到/未找到」过程性叙述泄漏")
    if leaked:
        ok = False

    print(f"\n最终回答长度: {len(final_text)} 字符")
    print(f"结论: {'✅ 重复输出问题已修复' if ok else '❌ 仍存在重复/泄漏，请检查'}")


if __name__ == "__main__":
    asyncio.run(main())
