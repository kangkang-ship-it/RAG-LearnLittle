"""
聊天会话与消息数据模型

对应 MySQL 表:
- chat_sessions: 聊天会话
- chat_messages: 聊天消息
- chat_summaries: 聊天摘要（里程碑压缩）

会话标题支持自动生成（LLM）和手动修改。
消息使用游标分页，支持幂等写入（idempotency_key 防重复）。
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, BigInteger, ForeignKey, JSON, func, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ChatSession(Base):
    """
    聊天会话模型
    
    存储会话元数据，消息通过 ChatMessage 关联。
    metadata 字段存储扩展信息：
    - title_generated_at: 标题生成时间（冻结机制）
    - title_frozen: 标题是否已冻结（不再自动更新）
    - model_name: 使用的模型名称
    - total_tokens: 累计 token 消耗
    - message_count: 消息总数
    
    关联关系：
    - 多对一 → User（所属用户）
    - 一对多 → ChatMessage（消息列表）
    """
    __tablename__ = "chat_sessions"
    
    # 主键：UUID
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    
    # 所属用户 ID（外键，级联删除）
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.uuid", ondelete="CASCADE"), nullable=False, index=True
    )
    
    # 会话标题（可自动生成或手动修改）
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新对话")
    
    # 扩展元数据（JSON 格式）
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSON, nullable=True, default=dict
    )
    
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    
    # 更新时间（新消息写入时更新，用于会话列表排序）
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # ========== 关联关系 ==========
    user = relationship("User", back_populates="chat_sessions")
    messages = relationship(
        "ChatMessage", back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at"
    )
    summary = relationship(
        "ChatSummary", back_populates="session",
        uselist=False, cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<ChatSession(id={self.id}, title={self.title[:20]})>"


class ChatMessage(Base):
    """
    聊天消息模型
    
    存储单条聊天消息，支持：
    - 幂等写入：idempotency_key 有 UNIQUE 约束，防止网络重试导致重复消息
    - Token 计数：记录每条消息的 token 消耗
    - 角色区分：user / assistant / system
    
    关联关系：
    - 多对一 → ChatSession（所属会话）
    """
    __tablename__ = "chat_messages"
    
    # 主键：自增 ID
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # 所属会话 ID（外键，级联删除）
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    
    # 消息角色：user / assistant / system
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    
    # 消息内容
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Token 消耗数量
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    
    # 幂等键（客户端生成 UUID，防止重复提交）
    idempotency_key: Mapped[str | None] = mapped_column(
        String(36), unique=True, nullable=True
    )
    
    # 创建时间（同时作为排序依据和游标分页的游标）
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    
    # ========== 关联关系 ==========
    session = relationship("ChatSession", back_populates="messages")
    
    def __repr__(self) -> str:
        return f"<ChatMessage(id={self.id}, role={self.role})>"

# 更新数据库中的每条对话的摘要信息
class ChatSummary(Base):
    """
    聊天摘要模型
    
    每个会话保持一条摘要记录，采用增量更新策略。
    last_message_id 记录摘要覆盖到的消息位置，
    下次摘要时仅需处理该 ID 之后的新消息。
    """
    __tablename__ = "chat_summaries"
    
    # 主键
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # 所属会话 ID（唯一约束，每个会话仅一条摘要）
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )
    
    # 摘要文本
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    
    # 摘要覆盖到的最后一条消息 ID
    last_message_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # 摘要版本号（增量更新递增）
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    # 摘要的 token 数（缓存）
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # ========== 关联关系 ==========
    session = relationship("ChatSession", back_populates="summary")
    
    def __repr__(self) -> str:
        return f"<ChatSummary(session_id={self.session_id}, version={self.version})>"
