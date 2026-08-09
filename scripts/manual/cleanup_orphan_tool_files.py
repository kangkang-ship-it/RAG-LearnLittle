"""
一次性运维脚本：清理历史孤儿 PPT/TTS 文件（会话删除 bug 修复前的残留）

背景：2026-08-09 前删除会话不清理 PPT/TTS 工具产出文件（bug 已修复），
历史删除的会话其物理文件仍残留在 data/ppt/、data/tts/ 下。
本脚本对比「数据库现存消息 attachments_json 的引用」与「磁盘文件」，
删除无引用文件。

用法（需本机 .env 配置 + MySQL/Redis 可用）：
    .venv/Scripts/python.exe -X utf8 scripts/manual/cleanup_orphan_tool_files.py            # dry-run 预览
    .venv/Scripts/python.exe -X utf8 scripts/manual/cleanup_orphan_tool_files.py --apply    # 真正删除

安全保证：
- 只删除未被任何现存消息引用的文件（引用中的文件即使 TTL 到期也由业务 TTL 管理）
- file_id 白名单校验（^[0-9a-f]{32}$），异常命名文件仅列出不删除
- dry-run 默认开启
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

# 脚本位于 scripts/manual/，需把项目根加入 sys.path 才能 import app.*
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select

from app.core.logger_handler import logger
from app.db.database import async_session_factory, engine
from app.models.chat import ChatMessage
from app.routers.tts_router import TTS_FILE_ROOT
from app.services.ppt_service import PPT_FILE_ROOT

_FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


async def collect_referenced_ids() -> set:
    """收集数据库现存消息引用的 ppt/tts file_id"""
    referenced: set = set()
    async with async_session_factory() as db:
        result = await db.execute(
            select(ChatMessage).where(ChatMessage.attachments_json.isnot(None))
        )
        for msg in result.scalars().all():
            for att in msg.attachments_json or []:
                if not isinstance(att, dict):
                    continue
                if att.get("file_type") in ("ppt", "tts") and att.get("file_id"):
                    referenced.add(str(att["file_id"]))
    logger.info(f"数据库现存引用: {len(referenced)} 个 ppt/tts file_id")
    return referenced


async def main(apply: bool) -> None:
    referenced = await collect_referenced_ids()

    # 未通过白名单校验的文件（异常命名，防御性仅列出）
    anomalous = []
    orphans = []
    for root_name in (PPT_FILE_ROOT, TTS_FILE_ROOT):
        root = Path(root_name)
        if not root.is_dir():
            continue
        for user_dir in root.iterdir():
            if not user_dir.is_dir():
                continue
            for f in user_dir.iterdir():
                if not f.is_file():
                    continue
                file_id = f.stem
                if not _FILE_ID_RE.match(file_id):
                    anomalous.append(f)
                elif file_id not in referenced:
                    orphans.append(f)

    print(f"\n=== 扫描结果 ===")
    print(f"无引用文件: {len(orphans)} 个")
    print(f"异常命名文件（不处理）: {len(anomalous)} 个")
    for f in anomalous[:10]:
        print(f"  [跳过] {f}")
    if len(anomalous) > 10:
        print(f"  ... 其余 {len(anomalous) - 10} 个省略")

    if not orphans:
        print("\n没有需要清理的孤儿文件 ✓")
        return

    if not apply:
        print("\n[dry-run] 以下文件将被删除（加 --apply 实际执行）:")
        for f in orphans[:50]:
            print(f"  {f}")
        if len(orphans) > 50:
            print(f"  ... 其余 {len(orphans) - 50} 个省略")
        return

    removed = 0
    failed = 0
    for f in orphans:
        try:
            f.unlink()
            removed += 1
        except OSError as e:
            failed += 1
            print(f"  [失败] {f}: {e}")
    print(f"\n已删除 {removed} 个，失败 {failed} 个")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理历史孤儿 PPT/TTS 文件")
    parser.add_argument("--apply", action="store_true", help="实际删除（默认仅预览）")
    args = parser.parse_args()

    asyncio.run(main(apply=args.apply))
