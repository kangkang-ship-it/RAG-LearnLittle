"""
笔记模板数据模型

对应 MySQL 表: note_templates
存储用户自定义的笔记模板骨架（Markdown / JSON Schema）。
"""

from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class NoteTemplate(Base):
    """
    笔记模板模型
    
    存储用户自定义模板，content_structure 字段保存模板骨架结构。
    支持按 category 分类和 sort_order 排序。
    
    关联关系：
    - 多对一 → User（所属用户）
    """
    __tablename__ = "note_templates"
    
    # 主键：自增 ID
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # 所属用户 ID（外键，级联删除）
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.uuid", ondelete="CASCADE"), nullable=False, index=True
    )
    
    # 模板名称
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    
    # 模板骨架结构（JSON 格式，包含 Markdown 模板或 JSON Schema）
    content_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    # 模板分类
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    
    # 排序权重（越小越靠前）
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # ========== 关联关系 ==========
    user = relationship("User", back_populates="note_templates")
    
    def __repr__(self) -> str:
        return f"<NoteTemplate(id={self.id}, name={self.name})>"
