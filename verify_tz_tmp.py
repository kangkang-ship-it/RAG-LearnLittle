# -*- coding: utf-8 -*-
"""时区修复验证：上传附件 → created_at 为 UTC → ttl=0 孤儿清理立即可删"""
from dotenv import load_dotenv
load_dotenv()
import asyncio, os
from sqlalchemy import select
from app.db.database import async_session_factory
from app.services.chat_attachment_service import ChatAttachmentService

async def main():
    # 直接调 save_upload（绕过 HTTP）
    from PIL import Image
    import io
    img = Image.new("RGB", (100, 100), (10, 20, 30))
    buf = io.BytesIO(); img.save(buf, format="PNG")

    async with async_session_factory() as db:
        att = await ChatAttachmentService().save_upload(db, "tz-test-user", "tz.png", buf.getvalue())
        await db.commit()
        print(f"上传: file_id={att.file_id[:8]}, created_at={att.created_at} (UTC={att.created_at is not None})")

    async with async_session_factory() as db:
        count = await ChatAttachmentService().cleanup_orphans(db, ttl_hours=0)
        await db.commit()
        print(f"孤儿清理(ttl=0): {count} 条")
        assert count == 1, "时区修复后 ttl=0 应立即清理刚上传的附件"
        print("PASS: created_at UTC + 孤儿清理时区一致")

asyncio.run(main())
