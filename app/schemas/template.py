"""
笔记模板相关 Pydantic Schema

定义笔记模板 CRUD、排序等接口的请求和响应模型。
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class NoteTemplateCreate(BaseModel):
    """创建笔记模板请求"""
    name: str = Field(..., min_length=1, max_length=200, description="模板名称")
    content_structure: Optional[dict] = Field(None, description="模板骨架结构（JSON）")
    category: Optional[str] = Field(None, max_length=100, description="模板分类")
    sort_order: int = Field(0, ge=0, description="排序权重")


class NoteTemplateUpdate(BaseModel):
    """更新笔记模板请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=200, description="模板名称")
    content_structure: Optional[dict] = Field(None, description="模板骨架结构")
    category: Optional[str] = Field(None, max_length=100, description="模板分类")
    sort_order: Optional[int] = Field(None, ge=0, description="排序权重")


class NoteTemplateResponse(BaseModel):
    """笔记模板响应"""
    id: int
    user_id: str
    name: str
    content_structure: Optional[dict] = None
    category: Optional[str] = None
    sort_order: int
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class NoteTemplateListResponse(BaseModel):
    """笔记模板列表响应"""
    templates: List[NoteTemplateResponse]
