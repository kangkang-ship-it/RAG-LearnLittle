"""
API 路由包

将所有路由模块集中在此处，供 main.py 统一导入注册。
"""

from app.routers import (
    health,
    user,
    chat,
    note_router,
    knowledge_router,
    review_router,
    note_template_router,
    usage,
    ppt_router,
    ppt_template_router,
    tts_router,
)

__all__ = [
    "health",
    "user",
    "chat",
    "note_router",
    "knowledge_router",
    "review_router",
    "note_template_router",
    "usage",
    "ppt_router",
    "ppt_template_router",
    "tts_router",
]
