"""
知识库相关 Pydantic Schema

定义知识库文档上传、列表、切片查看等接口的请求和响应模型。
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class KnowledgeDocumentResponse(BaseModel):
    """知识库文档响应"""
    id: int
    user_id: str
    filename: str
    file_size: int
    file_type: str
    md5_hash: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}


class KnowledgeDocumentListResponse(BaseModel):
    """知识库文档列表响应"""
    documents: List[KnowledgeDocumentResponse]
    total: int


class ChunkDetail(BaseModel):
    """文档切片详情"""
    chunk_id: str = Field(..., description="切片 ID")
    content: str = Field(..., description="切片文本内容")
    metadata: Optional[dict] = Field(None, description="切片元数据")


class ChunkListResponse(BaseModel):
    """文档切片列表响应"""
    document_id: int
    filename: str
    chunks: List[ChunkDetail]
    total: int
