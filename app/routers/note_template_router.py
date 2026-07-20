"""
笔记模板路由

端点：
- POST /note-template - 创建模板
- GET /note-template - 模板列表
- GET /note-template/{template_id} - 模板详情
- PUT /note-template/{template_id} - 更新模板
- DELETE /note-template/{template_id} - 删除模板
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.database import get_db
from app.schemas.template import (
    NoteTemplateCreate, NoteTemplateUpdate, NoteTemplateResponse, NoteTemplateListResponse,
)
from app.utils.auth_utils import get_current_user_id
from app.services.note_template_service import NoteTemplateService

router = APIRouter()

template_service = NoteTemplateService()


@router.post("/note-template", summary="创建模板")
async def create_template(
    data: NoteTemplateCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """创建新的笔记模板"""
    template = await template_service.create_template(db, user_id, data)
    return success_response(data=NoteTemplateResponse.model_validate(template).model_dump())


@router.get("/note-template", summary="模板列表")
async def list_templates(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的所有笔记模板"""
    templates = await template_service.list_templates(db, user_id)
    return success_response(data=NoteTemplateListResponse(
        templates=[NoteTemplateResponse.model_validate(t).model_dump() for t in templates],
    ).model_dump())


@router.get("/note-template/{template_id}", summary="模板详情")
async def get_template(
    template_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取单个模板详情"""
    template = await template_service.get_template(db, template_id, user_id)
    return success_response(data=NoteTemplateResponse.model_validate(template).model_dump())


@router.put("/note-template/{template_id}", summary="更新模板")
async def update_template(
    template_id: int,
    data: NoteTemplateUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """更新笔记模板"""
    template = await template_service.update_template(db, template_id, user_id, data)
    return success_response(data=NoteTemplateResponse.model_validate(template).model_dump())


@router.delete("/note-template/{template_id}", summary="删除模板")
async def delete_template(
    template_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """删除笔记模板"""
    await template_service.delete_template(db, template_id, user_id)
    return success_response(message="模板已删除")
