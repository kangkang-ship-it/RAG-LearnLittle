"""
PPT 模板数据模型（设计方案 §6.5）

对应 MySQL 表: ppt_templates
存储用户上传的 PPT 模板元数据（.pptx 文件本体在 data/ppt_templates/{user_id}/）。
模板是用户资产，永久保留（不进 TTL，区别于 data/ppt/ 临时产物）。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class PptTemplate(Base):
    """
    PPT 模板模型

    元数据：名称 / 文件大小 / 创建时间；文件本体按 {user_id}/{id}.pptx 落盘。

    关联关系：
    - 多对一 → User（所属用户，级联删除）
    """
    __tablename__ = "ppt_templates"

    # 主键：自增 ID（与 NoteTemplate 一致的整数主键）
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 所属用户 ID（外键，级联删除）
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.uuid", ondelete="CASCADE"), nullable=False, index=True
    )

    # 模板名称
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # 文件大小（字节）
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # 更新时间（与 NoteTemplate 保持一致，为未来重命名等编辑预留）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # 软删除标记（v1 仅上传后删除重传，不做回收站）
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # ========== 关联关系 ==========
    user = relationship("User", back_populates="ppt_templates")

    def __repr__(self) -> str:
        return f"<PptTemplate(id={self.id}, name={self.name})>"
