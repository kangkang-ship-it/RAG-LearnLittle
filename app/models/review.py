"""
回顾记录数据模型

对应 MySQL 表: review_records
实现间隔重复回顾功能，基于艾宾浩斯遗忘曲线算法。
回顾间隔：1 / 2 / 4 / 7 / 15 / 30 天
"""

from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ReviewRecord(Base):
    """
    回顾记录模型
    
    实现间隔重复回顾（Spaced Repetition）：
    - 每次回顾后根据 quality 评分调整下次回顾时间
    - interval_days 按艾宾浩斯曲线递增
    - next_review_at 用于查询今日待回顾的笔记
    - quality 字段为 SM-2 算法升级预留
    
    关联关系：
    - 多对一 → Note（关联笔记）
    - 多对一 → User（所属用户）
    """
    __tablename__ = "review_records"
    
    # 主键：自增 ID
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # 关联笔记 ID（外键，级联删除）
    note_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    
    # 所属用户 ID（外键，级联删除）
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.uuid", ondelete="CASCADE"), nullable=False, index=True
    )
    
    # 已回顾次数
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # 当前间隔天数（按艾宾浩斯曲线：1/2/4/7/15/30 天）
    interval_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
    # 回顾质量评分（0-5，为 SM-2 算法升级预留）
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # 下次回顾时间
    next_review_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    
    # 上次实际完成回顾的时间
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # ========== 关联关系 ==========
    note = relationship("Note", back_populates="review_records")
    user = relationship("User", back_populates="review_records")
    
    def __repr__(self) -> str:
        return f"<ReviewRecord(id={self.id}, note_id={self.note_id}, next_review={self.next_review_at})>"
