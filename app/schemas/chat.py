"""
聊天相关 Pydantic Schema

定义 Agent 对话、RAG 查询、会话管理等接口的请求和响应模型。
"""

from datetime import datetime
from typing import Literal, Optional, List, TypedDict

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Agent 对话请求"""
    session_id: Optional[str] = Field(None, description="会话 ID（为空则创建新会话）")
    message: str = Field(..., min_length=1, max_length=10000, description="用户消息")
    idempotency_key: Optional[str] = Field(None, description="幂等键（防重复提交）")


class RAGRequest(BaseModel):
    """RAG 查询请求"""
    query: str = Field(..., min_length=1, description="查询内容")
    top_k: int = Field(3, ge=1, le=10, description="检索文档数量")
    use_hyde: bool = Field(True, description="是否使用 HyDE 技术")


class ChatMessageResponse(BaseModel):
    """聊天消息响应"""
    id: int
    session_id: str
    role: str
    content: str
    token_count: Optional[int] = 0
    created_at: datetime
    
    model_config = {"from_attributes": True}


class ChatSessionResponse(BaseModel):
    """聊天会话响应"""
    id: str
    title: str
    metadata: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    
    model_config = {"from_attributes": True}


class ChatSessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[ChatSessionResponse]


class MessageListResponse(BaseModel):
    """消息列表响应（游标分页）"""
    messages: List[ChatMessageResponse]
    has_more: bool = Field(..., description="是否还有更多消息")
    next_cursor: Optional[str] = Field(None, description="下一页游标（created_at 值）")


class SessionTitleUpdate(BaseModel):
    """会话标题修改请求"""
    title: str = Field(..., min_length=1, max_length=200, description="新标题")


# ============================================================
# Plan-and-Execute SSE 事件类型定义
# ============================================================

class PlanStartEvent(TypedDict):
    """计划开始事件"""
    type: Literal["plan_start"]
    goal: str
    total_steps: int


class PlanStepEvent(TypedDict):
    """单个步骤声明事件"""
    type: Literal["plan_step"]
    step: int
    action: str
    status: Literal["pending", "running", "completed"]


class PlanStepStartEvent(TypedDict):
    """步骤开始执行事件"""
    type: Literal["plan_step_start"]
    step: int
    action: str


class PlanStepEndEvent(TypedDict):
    """步骤执行完成事件"""
    type: Literal["plan_step_end"]
    step: int
    result: str


class PlanSynthesizeEvent(TypedDict):
    """进入综合阶段事件"""
    type: Literal["plan_synthesize"]
    content: str


class PlanCompleteEvent(TypedDict):
    """计划全部完成事件"""
    type: Literal["plan_complete"]
    total_steps: int
    completed_steps: int


class PlanFallbackEvent(TypedDict):
    """Plan 失败降级事件"""
    type: Literal["plan_fallback"]
    reason: str
