"""
用量统计路由（P2-2 成本账单）

端点：
- GET /usage/summary - 当前用户的模型调用用量/费用汇总（可按会话/时间范围过滤）
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.database import get_db
from app.services.usage_service import get_usage_summary
from app.utils.auth_utils import get_current_user_id

router = APIRouter()


@router.get("/usage/summary", summary="模型调用用量与费用汇总")
async def usage_summary(
    days: int = Query(30, ge=1, le=365, description="统计天数（默认 30）"),
    session_id: str | None = Query(None, description="按会话过滤（不传则汇总全部会话）"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """返回当前用户的模型调用次数 / token / 估算费用 / 平均延迟（按阶段与模型分组）"""
    data = await get_usage_summary(db, user_id, session_id=session_id, days=days)
    return success_response(data=data)
