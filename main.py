"""
RAG LearnLittle — 智能笔记助手 · 应用入口

FastAPI 应用的生命周期管理：
- 启动阶段：加载环境变量、初始化数据库、连接 Redis、后台初始化模型
- 中间件：CORS、请求处理时间、全局异常处理
- 关闭阶段：释放数据库和 Redis 连接池
"""

import os
import time
import asyncio
from contextlib import asynccontextmanager

# 必须在所有 app 导入之前加载 .env，否则模块级 os.getenv 会读到默认值
from dotenv import load_dotenv
load_dotenv()

# 强制 HuggingFace 离线模式（阻止在线下载模型，仅使用本地缓存）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.logger_handler import logger
from app.core.failed_response_register import register_exception_handlers
from app.db.database import init_db, close_db
from app.db.redis_client import init_redis, close_redis


# ========== 后台初始化管理器 ==========

class BackgroundInitManager:
    """
    后台初始化管理器
    
    在 FastAPI 启动后通过 asyncio.create_task 在后台异步初始化重型资源。
    分三个阶段顺序执行：
    1. AI 模型（Chat + Embedding + Vision）
    2. NoteService + ChromaDB
    3. 重排序模型
    
    每个阶段完成后设置 asyncio.Event，路由层通过 event.wait() 阻塞等待。
    """
    
    def __init__(self):
        """初始化阶段事件"""
        self.stage1_complete = asyncio.Event()  # AI 模型就绪
        self.stage2_complete = asyncio.Event()  # NoteService + ChromaDB 就绪
        self.stage3_complete = asyncio.Event()  # 重排序模型就绪
        
        # 管理的实例
        self.chat_model = None
        self.embed_model = None
        self.vision_model = None
        self.note_service = None
        self.reorder_service = None
    
    async def run(self):
        """
        执行后台初始化（三个阶段）
        """
        try:
            # 阶段 1: 初始化 AI 模型
            logger.info("后台初始化 - 阶段 1: AI 模型...")
            await self._init_models()
            self.stage1_complete.set()
            logger.info("后台初始化 - 阶段 1 完成 ✓")
            
            # 阶段 2: 初始化 NoteService + ChromaDB
            logger.info("后台初始化 - 阶段 2: NoteService + ChromaDB...")
            await self._init_services()
            self.stage2_complete.set()
            logger.info("后台初始化 - 阶段 2 完成 ✓")
            
            # 阶段 3: 初始化重排序模型
            logger.info("后台初始化 - 阶段 3: 重排序模型...")
            await self._init_reranker()
            self.stage3_complete.set()
            logger.info("后台初始化 - 阶段 3 完成 ✓")
            
        except Exception as e:
            logger.error(f"后台初始化失败: {e}")
    
    async def _init_models(self):
        """初始化 AI 模型（Chat + Embedding）"""
        try:
            from app.utils.factory import create_chat_model, create_embed_model
            self.chat_model = create_chat_model()
            self.embed_model = create_embed_model()
            logger.info("AI 模型初始化成功")
        except Exception as e:
            logger.warning(f"AI 模型初始化失败（部分功能不可用）: {e}")
    
    async def _init_services(self):
        """初始化 NoteService 和 ChromaDB"""
        try:
            from app.rag.vector_store import VectorStoreService
            from app.services.note_service import NoteService
            
            vector_store = VectorStoreService(embed_model=self.embed_model)
            self.note_service = NoteService(
                vector_store=vector_store,
                chat_model=self.chat_model,
            )
            logger.info("NoteService + ChromaDB 初始化成功")
        except Exception as e:
            logger.warning(f"NoteService 初始化失败: {e}")
    
    async def _init_reranker(self):
        """初始化重排序模型（带 30 秒超时保护）"""
        try:
            from sentence_transformers import CrossEncoder
            from app.utils.config import get_chroma_config
                
            config = get_chroma_config()
            model_name = config.get("reranker", {}).get("model_name", "BAAI/bge-reranker-v2-m3")
                
            # 在线程池中加载模型（避免阻塞事件循环），带超时保护
            loop = asyncio.get_event_loop()
            self.reorder_service = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: CrossEncoder(model_name)),
                timeout=30
            )
            logger.info(f"重排序模型初始化成功: {model_name}")
        except asyncio.TimeoutError:
            logger.warning("重排序模型初始化超时（30s），跳过。知识库重排序功能不可用。")
        except Exception as e:
            logger.warning(f"重排序模型初始化失败: {e}")


# 全局后台初始化管理器
init_manager = BackgroundInitManager()


# ========== FastAPI 应用 ==========

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    
    启动阶段：
    1. 初始化数据库表结构
    2. 连接 Redis
    3. 后台异步初始化模型和重型资源
    
    关闭阶段：
    1. 关闭 Redis 连接池
    2. 关闭数据库连接池
    """
    # ===== 启动阶段 =====
    logger.info("=" * 50)
    logger.info("RAG LearnLittle 启动中...")
    logger.info("=" * 50)
    
    # 1. 初始化数据库
    await init_db()
    
    # 2. 连接 Redis
    redis = await init_redis()
    app.state.redis = redis
    
    # 3. 创建测试用户（本地开发用）
    await _create_test_user()
    
    # 4. 后台异步初始化重型资源
    asyncio.create_task(init_manager.run())
    
    logger.info("应用启动完成，后台初始化进行中...")
    
    yield
    
    # ===== 关闭阶段 =====
    logger.info("应用关闭中...")
    await close_redis()
    await close_db()
    logger.info("应用已关闭")


async def _create_test_user():
    """
    创建测试用户 admin/admin1234（仅本地开发环境）
    
    如果用户已存在则跳过。
    """
    from app.db.database import async_session_factory
    from app.models.user import User
    from app.utils.auth_utils import hash_password
    from sqlalchemy import select
    
    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            logger.info("测试用户 admin 已存在，跳过创建")
            return
        
        user = User(
            username="admin",
            password=hash_password("admin1234"),
            email="admin@raglearn.local",
        )
        session.add(user)
        await session.commit()
        logger.info("测试用户创建成功: admin / admin1234")


# 创建 FastAPI 应用
app = FastAPI(
    title="RAG LearnLittle",
    description="AI 驱动的个人知识管理工具 — 智能笔记助手 API",
    version="1.0.0",
    lifespan=lifespan,
)


# ========== 中间件 ==========

# CORS 中间件
cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求处理时间中间件
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """
    记录每个请求的处理时间，添加到响应头 X-Process-Time 中。
    同时记录请求日志（method + path + status + duration_ms）。
    """
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}"
    
    # 记录请求日志
    logger.info(
        f"{request.method} {request.url.path} - "
        f"status={response.status_code} "
        f"duration={process_time * 1000:.1f}ms"
    )
    
    return response


# 注册全局异常处理器
register_exception_handlers(app)


# ========== 路由注册 ==========

from app.routers import (
    health,
    user,
    chat,
    note_router,
    knowledge_router,
    review_router,
    note_template_router,
)

# 健康检查（不需要认证）
app.include_router(health.router, tags=["Health"])

# 业务路由（统一 /api/v1 前缀）
API_PREFIX = "/api/v1"

app.include_router(user.router, prefix=API_PREFIX, tags=["User & Auth"])
app.include_router(chat.router, prefix=API_PREFIX, tags=["Chat"])
app.include_router(note_router.router, prefix=API_PREFIX, tags=["Note"])
app.include_router(knowledge_router.router, prefix=API_PREFIX, tags=["Knowledge"])
app.include_router(review_router.router, prefix=API_PREFIX, tags=["Review"])
app.include_router(note_template_router.router, prefix=API_PREFIX, tags=["Note Template"])

# 静态文件服务（头像访问）
# 确保头像存储目录存在
avatar_dir = os.path.join("data", "avatars")
os.makedirs(avatar_dir, exist_ok=True)
app.mount("/static/avatars", StaticFiles(directory=avatar_dir), name="avatars")


# ========== 启动入口 ==========

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
