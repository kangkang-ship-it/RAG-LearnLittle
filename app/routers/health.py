"""
健康检查路由

端点：
- GET /health     - 存活探针（liveness）：进程存活即 200
- GET /ready      - 就绪探针（readiness）：后台初始化完成 + MySQL/Redis 连通才 200
- GET /metrics    - Prometheus 指标（审查 P1-2）

/health 始终返回 200，确认进程存活。
/ready 在后台初始化全部完成后才返回 200，供负载均衡器/容器编排就绪探测。
"""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.core.success_response import success_response

router = APIRouter()


@router.get("/health", summary="存活探针")
async def health_check():
    """
    存活探针（Liveness Probe）

    始终返回 200，确认应用进程正在运行。
    用于 Kubernetes livenessProbe 或负载均衡器健康检查。
    """
    return success_response(data={"status": "healthy"})


async def _check_dependencies() -> dict:
    """
    依赖连通性探测（MySQL SELECT 1 + Redis PING，各 2 秒超时）

    Returns:
        {"database": bool, "redis": bool}
    """
    from app.db.database import engine
    from app.db.redis_client import redis_pool

    result = {"database": False, "redis": False}

    try:
        async with asyncio.timeout(2):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        result["database"] = True
    except Exception:
        pass  # 失败保持 False，由调用方决定是否 503

    try:
        if redis_pool is not None:
            async with asyncio.timeout(2):
                await redis_pool.ping()
            result["redis"] = True
    except Exception:
        pass

    return result


@router.get("/ready", summary="就绪探针")
async def readiness_check(request: Request):
    """
    就绪探针（Readiness Probe）

    满足以下条件才返回 200：
    1. 后台初始化（模型加载、ChromaDB、重排序模型）已完成
    2. MySQL / Redis 连通

    未就绪时返回 503 并附失败原因，负载均衡器将不会把流量路由到该实例。

    用于 Kubernetes readinessProbe。
    """
    # 检查后台初始化是否完成（init_complete 由 main.py lifespan 中
    # _run_init_and_mark_ready 在 init_manager.run() 结束后置位）
    init_complete = getattr(request.app.state, "init_complete", False)
    init_error = getattr(request.app.state, "init_error", None)

    deps = await _check_dependencies()

    if init_complete and deps["database"] and deps["redis"]:
        return success_response(data={"status": "ready", "dependencies": deps})

    messages = []
    if not init_complete:
        messages.append(init_error or "后台初始化进行中")
    if not deps["database"]:
        messages.append("MySQL 不可达")
    if not deps["redis"]:
        messages.append("Redis 不可达")

    return JSONResponse(
        status_code=503,
        content=success_response(data={
            "status": "initializing",
            "message": "；".join(messages),
            "dependencies": deps,
        }),
    )


@router.get("/metrics", summary="Prometheus 指标", include_in_schema=False)
async def metrics():
    """
    Prometheus 指标端点（抓取目标）

    输出 prometheus_client 格式文本，含 Python/进程基础指标与
    自定义 HTTP 请求指标（app/core/metrics.py）。
    """
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
