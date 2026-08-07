"""
PPT 模板路由（设计方案 §6.5）

端点（路径与响应风格对齐 note_template_router 先例：单数 /ppt-template + success_response）：
- POST /ppt-template/upload - 上传模板（multipart：file + name）
- GET /ppt-template - 模板列表
- DELETE /ppt-template/{template_id} - 删除模板
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.database import get_db
from app.services.ppt_template_service import PptTemplateService
from app.utils.auth_utils import get_current_user_id

router = APIRouter()

template_service = PptTemplateService()


@router.post("/ppt-template/upload", summary="上传 PPT 模板")
async def upload_template(
    file: UploadFile = File(...),
    name: str = Form(""),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """上传 .pptx 模板（魔数/大小/数量配额校验 → 落盘 → 写 DB）"""
    try:
        template = await template_service.create_template(db, user_id, file, name)
    except ValueError as e:
        from app.core.failed_response import BusinessError, ErrorCode

        raise BusinessError(code=ErrorCode.INVALID_PARAM, http_status=400, message=str(e))
    return success_response(data={
        "id": template.id,
        "name": template.name,
        "file_size": template.file_size,
        "created_at": template.created_at.isoformat() if template.created_at else None,
    })


@router.get("/ppt-template", summary="PPT 模板列表")
async def list_templates(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的 PPT 模板列表（按创建时间倒序）"""
    templates = await template_service.list_templates(db, user_id)
    return success_response(data={
        "templates": [{
            "id": t.id,
            "name": t.name,
            "file_size": t.file_size,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in templates],
    })


@router.delete("/ppt-template/{template_id}", summary="删除 PPT 模板")
async def delete_template(
    template_id: int,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """删除模板（软删除记录 + 删除文件）"""
    await template_service.delete_template(db, template_id, user_id)
    return success_response(message="模板已删除")
