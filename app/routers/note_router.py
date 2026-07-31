"""
笔记路由

端点：
- POST /note - 创建笔记
- GET /note - 笔记列表（分页）
- GET /note/{note_id} - 笔记详情
- PUT /note/{note_id} - 更新笔记
- DELETE /note/{note_id} - 删除笔记（软删除）
- POST /note/search - 语义搜索
- POST /note/batch - 批量操作
- POST /note/autocomplete - AI 内联补全
- POST /note/write-assistant - AI 写作辅助
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.core.rate_limit import rate_limit
from app.db.database import get_db
from app.schemas.note import (
    NoteCreate, NoteUpdate, NoteResponse, NoteListResponse,
    NoteSearchRequest, NoteSearchResponse, BatchOperation,
    AutocompleteRequest, WriteAssistantRequest,
)
from app.utils.auth_utils import get_current_user_id
router = APIRouter()


def _get_note_service():
    """获取 NoteService 实例（从后台初始化管理器获取已注入 vector_store 和 chat_model 的实例）"""
    from main import init_manager
    if init_manager.note_service is not None:
        return init_manager.note_service
    # 后台初始化未完成，返回无向量/模型的基础实例（降级模式）
    from app.services.note_service import NoteService
    return NoteService()


@router.post("/note", summary="创建笔记")
async def create_note(
    data: NoteCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """创建新笔记，自动触发向量双写和异步标签生成"""
    note = await _get_note_service().create_note(db, user_id, data)
    return success_response(data=NoteResponse.model_validate(note).model_dump())


@router.get("/note", summary="笔记列表")
async def list_notes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str = Query(None),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """分页获取笔记列表，支持按分类过滤"""
    notes, total = await _get_note_service().list_notes(db, user_id, page, page_size, category)
    return success_response(data=NoteListResponse(
        notes=[NoteResponse.model_validate(n).model_dump() for n in notes],
        total=total, page=page, page_size=page_size,
    ).model_dump())


@router.get("/note/{note_id}", summary="笔记详情")
async def get_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取单个笔记详情"""
    note = await _get_note_service().get_note(db, note_id, user_id)
    return success_response(data=NoteResponse.model_validate(note).model_dump())


@router.put("/note/{note_id}", summary="更新笔记")
async def update_note(
    note_id: str,
    data: NoteUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """更新笔记内容，同步更新向量"""
    note = await _get_note_service().update_note(db, note_id, user_id, data)
    return success_response(data=NoteResponse.model_validate(note).model_dump())


@router.delete("/note/{note_id}", summary="删除笔记")
async def delete_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """软删除笔记（移入回收站）"""
    await _get_note_service().delete_note(db, note_id, user_id)
    return success_response(message="笔记已删除")


@router.post("/note/search", summary="语义搜索")
async def search_notes(
    data: NoteSearchRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """基于 ChromaDB 的语义搜索"""
    results = await _get_note_service().semantic_search(db, user_id, data.query, data.top_k)
    return success_response(data={
        "query": data.query,
        "results": [
            {"note": NoteResponse.model_validate(n).model_dump(), "score": s}
            for n, s in results
        ]
    })


@router.post("/note/batch", summary="批量操作")
async def batch_operation(
    data: BatchOperation,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    批量操作笔记（删除/置顶/取消置顶/移动分类）

    使用显式 commit 确保变更在响应返回前已持久化到 MySQL。
    不依赖 get_db() 的 auto-commit，避免 cleanup 阶段异常导致变更丢失。
    """
    from app.core.logger_handler import logger
    note_service = _get_note_service()

    success_ids = []
    errors = []

    for note_id in data.note_ids:
        try:
            if data.operation == 'delete':
                await note_service.delete_note(db, note_id, user_id)
            elif data.operation == 'pin':
                await note_service.pin_note(db, note_id, user_id)
            elif data.operation == 'unpin':
                await note_service.unpin_note(db, note_id, user_id)
            elif data.operation == 'move':
                await note_service.move_note(db, note_id, user_id, data.target_category)
            else:
                raise ValueError(f"未知的操作类型: {data.operation}")
            success_ids.append(note_id)
        except Exception as e:
            errors.append({"note_id": note_id, "error": str(e)})
            logger.warning(f"批量操作单条失败: note_id={note_id}, error={e}")

    # ★ 显式 commit：确保变更在响应返回前持久化到 MySQL
    # commit 后 SQLAlchemy autobegin 开启新事务，get_db() 的后续 commit 是空操作
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"批量操作事务提交失败: operation={data.operation}, error={e}")
        from app.core.failed_response import BusinessError, ErrorCode
        raise BusinessError(
            code=ErrorCode.INTERNAL_ERROR, http_status=500,
            message=f"批量操作提交失败: {e}"
        )

    logger.info(
        f"批量操作完成: operation={data.operation}, "
        f"success={len(success_ids)}, errors={len(errors)}"
    )

    return success_response(data={
        "operation": data.operation,
        "total": len(data.note_ids),
        "success_count": len(success_ids),
        "error_count": len(errors),
        "errors": errors if errors else None,
    }, message=f"批量{data.operation}操作完成：成功 {len(success_ids)} 篇，失败 {len(errors)} 篇")


@router.post("/note/autocomplete", summary="AI 内联补全")
async def autocomplete(
    data: AutocompleteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """AI 内联补全（根据上下文续写）"""
    # TODO: 集成 LLM 补全
    return success_response(data={"completion": "AI 补全功能待集成"})


@router.post("/note/write-assistant", summary="AI 写作辅助")
async def write_assistant(
    data: WriteAssistantRequest,
    user_id: str = Depends(get_current_user_id),
):
    """AI 写作辅助（续写/扩写/摘要）"""
    # TODO: 集成 LLM 写作辅助
    return success_response(data={"result": "AI 写作辅助功能待集成"})
