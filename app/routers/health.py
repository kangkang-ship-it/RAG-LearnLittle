"""
健康检查路由

端点：
- GET /health - 存活探针（liveness）
- GET /ready - 就绪探针（readiness）

/health 始终返回 200，确认进程存活。
/ready 在后台初始化全部完成后才返回 200，供负载均衡器/容器编排就绪探测。
"""

from fastapi import APIRouter, Request

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


@router.get("/ready", summary="就绪探针")
async def readiness_check(request: Request):
    """
    就绪探针（Readiness Probe）
    
    在后台初始化（模型加载、ChromaDB、重排序模型）全部完成后才返回 200。
    未完成时返回 503，负载均衡器将不会把流量路由到该实例。
    
    用于 Kubernetes readinessProbe。
    """
    # 检查后台初始化是否完成
    init_complete = getattr(request.app.state, "init_complete", False)
    
    if not init_complete:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content=success_response(data={"status": "initializing", "message": "后台初始化进行中"})
        )
    
    return success_response(data={"status": "ready"})
