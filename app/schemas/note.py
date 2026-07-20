"""
笔记相关 Pydantic Schema

定义笔记 CRUD、语义搜索、自动标签、写作辅助等接口的请求和响应模型。
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    """创建笔记请求"""
    title: str = Field(..., min_length=1, max_length=500, description="笔记标题")
    content: str = Field(..., min_length=1, description="笔记内容（Markdown）")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    category: Optional[str] = Field(None, max_length=100, description="分类")
    is_pinned: bool = Field(False, description="是否置顶")


class NoteUpdate(BaseModel):
    """更新笔记请求"""
    title: Optional[str] = Field(None, min_length=1, max_length=500, description="笔记标题")
    content: Optional[str] = Field(None, min_length=1, description="笔记内容")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    category: Optional[str] = Field(None, max_length=100, description="分类")
    is_pinned: Optional[bool] = Field(None, description="是否置顶")


class NoteResponse(BaseModel):
    """笔记响应"""
    id: str
    user_id: str
    title: str
    content: str
    tags: Optional[List[str]] = None
    category: Optional[str] = None
    is_pinned: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class NoteListResponse(BaseModel):
    """笔记列表响应（分页）"""
    notes: List[NoteResponse]
    total: int
    page: int
    page_size: int


class NoteSearchRequest(BaseModel):
    """语义搜索请求"""
    query: str = Field(..., min_length=1, description="搜索关键词")
    top_k: int = Field(5, ge=1, le=20, description="返回结果数量")


class NoteSearchResult(BaseModel):
    """语义搜索结果项"""
    note: NoteResponse
    score: float = Field(..., description="相似度分数")


class NoteSearchResponse(BaseModel):
    """语义搜索响应"""
    results: List[NoteSearchResult]
    query: str


class AutocompleteRequest(BaseModel):
    """AI 内联补全请求"""
    content: str = Field(..., description="当前笔记内容")
    cursor_position: int = Field(0, ge=0, description="光标位置")


class WriteAssistantRequest(BaseModel):
    """AI 写作辅助请求"""
    content: str = Field(..., description="笔记内容")
    mode: str = Field("continue", description="模式：continue(续写) / expand(扩写) / summary(摘要)")


class BatchOperation(BaseModel):
    """批量操作请求"""
    note_ids: List[str] = Field(..., description="笔记 ID 列表")
    operation: str = Field(..., description="操作类型：delete / pin / unpin / move")
    target_category: Optional[str] = Field(None, description="目标分类（move 操作时使用）")
