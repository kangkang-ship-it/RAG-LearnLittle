"""
用户数据模型

对应 MySQL 表: users
存储用户基本信息、认证凭据和个人资料。
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    """
    用户模型
    
    存储用户账号信息，包括：
    - 登录凭据（username + bcrypt 密码哈希）
    - 个人资料（avatar、bio）
    - 账户状态（status：active/banned）
    
    关联关系：
    - 一对多 → Note（笔记）
    - 一对多 → ChatSession（聊天会话）
    - 一对多 → ReviewRecord（回顾记录）
    - 一对多 → NoteTemplate（笔记模板）
    - 一对多 → KnowledgeDocument（知识库文档）
    """
    __tablename__ = "users"
    
    # 主键：UUID
    uuid: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    
    # 用户名（唯一）
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    
    # 邮箱（唯一，可选）
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)

    # 邮箱是否已验证（注册/修改邮箱验证通过后为 True）
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 密码哈希（bcrypt）
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # 头像 URL
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    
    # 个人简介
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # 账户状态：active / banned
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    
    # ========== 关联关系 ==========
    notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    review_records = relationship("ReviewRecord", back_populates="user", cascade="all, delete-orphan")
    note_templates = relationship("NoteTemplate", back_populates="user", cascade="all, delete-orphan")
    ppt_templates = relationship("PptTemplate", back_populates="user", cascade="all, delete-orphan")
    knowledge_documents = relationship("KnowledgeDocument", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<User(id={self.uuid}, username={self.username})>"
