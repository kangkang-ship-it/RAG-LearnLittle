"""
PPT 模板服务（设计方案 §6.5）

管理用户上传的 PPT 模板（.pptx）：
- 上传：.pptx 魔数校验（zip 头 PK\x03\x04）+ 大小 ≤ max_template_size_mb
  + 每用户 ≤ max_templates_per_user → 落盘 data/ppt_templates/{user_id}/{id}.pptx
  → 写 MySQL ppt_templates 表（软删除标记 deleted_at）
- 列表 / 删除（软删除记录 + 删文件）
- resolve_template_path：归属校验 + 返回文件路径（PptService.generate 调用，
  方案 A 构造注入，§6.5）

参照模式：note_template_service（DB CRUD）+ chat_attachment_service（文件落盘/校验）。
模板是用户资产，永久保留（不进 TTL，区别于 data/ppt/ 临时产物）。
"""
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.models.ppt_template import PptTemplate

# 模板存储根目录（相对项目根）
PPT_TEMPLATE_ROOT = os.getenv("PPT_TEMPLATE_ROOT", os.path.join("data", "ppt_templates"))

# .pptx 本质是 zip 压缩包，魔数为 PK\x03\x04
_PPTX_MAGIC = b"PK\x03\x04"


class PptTemplateService:
    """PPT 模板服务（轻量对象：只读配置 + 目录初始化，阶段 0 同步创建）"""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        os.makedirs(PPT_TEMPLATE_ROOT, exist_ok=True)

    # ========== 存储路径 ==========

    @staticmethod
    def _template_path(user_id: str, template_id: int) -> Path:
        """模板文件路径（相对项目根）"""
        return Path(PPT_TEMPLATE_ROOT) / user_id / f"{template_id}.pptx"

    # ========== 上传 ==========

    async def create_template(
        self, db: AsyncSession, user_id: str, file: UploadFile, name: str = ""
    ) -> PptTemplate:
        """
        上传并保存 PPT 模板（魔数/大小/配额校验 → 落盘 → 写 DB）

        Args:
            db: 数据库会话
            user_id: 当前用户 ID
            file: 上传的 .pptx 文件
            name: 模板名称（为空时取文件名）

        Returns:
            创建的模板记录

        Raises:
            ValueError: 校验失败（消息面向用户）
        """
        content = await file.read()
        if not content:
            raise ValueError("文件内容为空")

        # ① 魔数校验（防伪装扩展名的非 zip 文件）
        if content[:4] != _PPTX_MAGIC:
            raise ValueError("文件格式不正确，请上传 .pptx 文件")

        # ② 大小校验
        max_size_mb = self.config.get("max_template_size_mb", 10)
        if len(content) > max_size_mb * 1024 * 1024:
            raise ValueError(f"模板文件过大（上限 {max_size_mb}MB）")

        # ③ 每用户数量配额（不含已软删除的）
        max_templates = self.config.get("max_templates_per_user", 20)
        count = await db.scalar(
            select(func.count(PptTemplate.id)).where(
                PptTemplate.user_id == user_id,
                PptTemplate.deleted_at.is_(None),
            )
        )
        if (count or 0) >= max_templates:
            raise ValueError(f"模板数量已达上限（{max_templates} 个），请先删除不再使用的模板")

        # ④ 落盘（先 flush 拿自增 id 作文件名）
        template = PptTemplate(
            user_id=user_id,
            name=name.strip() or (file.filename or "未命名模板"),
            file_size=len(content),
        )
        db.add(template)
        await db.flush()

        # 回填 server_default 生成的 created_at：
        # 不 refresh 的话该属性从未加载，响应序列化访问时会触发惰性加载
        # （async 会话在 greenlet 外执行 IO → MissingGreenlet）
        await db.refresh(template)

        path = self._template_path(user_id, template.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

        # 不显式 commit：事务由 get_db 依赖统一提交（与 note_template_service 模式一致；
        # 显式 commit 会触发 expire_on_commit，后续访问属性同样触发惰性加载）
        logger.info(f"PPT 模板上传: template_id={template.id}, user={user_id[:8]}, "
                    f"size={len(content)}")
        return template

    # ========== 查询 / 删除 ==========

    async def list_templates(
        self, db: AsyncSession, user_id: str
    ) -> List[PptTemplate]:
        """获取用户模板列表（按创建时间倒序）"""
        result = await db.execute(
            select(PptTemplate)
            .where(PptTemplate.user_id == user_id, PptTemplate.deleted_at.is_(None))
            .order_by(PptTemplate.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_template(
        self, db: AsyncSession, template_id: int, user_id: str
    ) -> None:
        """删除模板（软删除记录 + 删除文件）"""
        result = await db.execute(
            update(PptTemplate)
            .where(
                PptTemplate.id == template_id,
                PptTemplate.user_id == user_id,
                PptTemplate.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now())
        )
        if result.rowcount == 0:
            from app.core.failed_response import BusinessError, ErrorCode

            raise BusinessError(code=ErrorCode.NOTE_NOT_FOUND, http_status=404,
                                message="模板不存在或无权操作")
        try:
            self._template_path(user_id, template_id).unlink(missing_ok=True)
        except OSError as e:
            logger.warning(f"PPT 模板文件删除失败: template_id={template_id}, err={e}")
        # 不显式 commit：事务由 get_db 依赖统一提交（与 create_template 一致）
        logger.info(f"PPT 模板删除: template_id={template_id}, user={user_id[:8]}")

    # ========== 归属解析（PptService 调用，§4.3 ①'） ==========

    async def resolve_template_path(
        self, db: AsyncSession, user_id: str, template_id: str
    ) -> Optional[str]:
        """
        归属校验 + 返回模板文件路径（设计方案 §6.5）

        Args:
            db: 数据库会话
            user_id: 当前用户 ID
            template_id: 模板 ID（字符串，工具参数惯例 §4.1；DB 主键为整数，
                内部 int() 转换）

        Returns:
            模板文件绝对路径；非法 ID / 越权 / 不存在 / 文件缺失 → None
            （PptService 收到 None 即降级默认版式，不阻断生成，§5.6 三档兜底第 1 档）
        """
        try:
            tid = int(template_id)
        except (TypeError, ValueError):
            logger.warning(f"PPT 模板 ID 非法: {template_id!r}")
            return None

        result = await db.execute(
            select(PptTemplate).where(
                PptTemplate.id == tid,
                PptTemplate.user_id == user_id,
                PptTemplate.deleted_at.is_(None),
            )
        )
        template = result.scalar_one_or_none()
        if template is None:
            logger.warning(f"PPT 模板越权/不存在: template_id={tid}, user={user_id[:8]}")
            return None

        path = self._template_path(user_id, tid)
        if not path.exists():
            logger.warning(f"PPT 模板文件缺失: {path}")
            return None
        return str(path)
