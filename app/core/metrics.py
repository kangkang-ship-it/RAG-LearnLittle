"""
Prometheus 指标采集（审查 P1-2：无 metrics 端点，生产无任何指标）

- HTTP 请求计数 + 耗时直方图（纯 ASGI 中间件采集）
- /metrics 端点由 health 路由暴露（prometheus_client 默认附带 Python/进程指标）
- 路由按匹配到的路由模板打标签（避免 file_id 等动态段造成基数爆炸）

实现说明：
- 纯 ASGI 中间件（不继承 BaseHTTPMiddleware）：后者会缓存/包装流式响应，
  对 SSE 输出（/chat/query 等）有干扰；纯 ASGI 只透传事件，零开销。
- 状态码从 http.response.start 事件捕获（响应头发出后抛异常的场景不重复计数）。

接入：main.py `app.add_middleware(MetricsMiddleware)`；health.py 提供 GET /metrics。
"""

import time
from typing import Any, Awaitable, Callable, Dict

from prometheus_client import Counter, Histogram

# HTTP 请求指标（method/path/status 标签；path 用路由模板，控制基数）
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests processed",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    # LLM/SSE 场景下长耗时请求常见，量程放宽到 60s
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

# 业务指标（后续可扩展：model_trace 失败数、rate_limit 命中数、MCP 工具调用计数等）

# ASGI 类型别名
Scope = Dict[str, Any]
Receive = Callable[[], Awaitable[Dict[str, Any]]]
Send = Callable[[Dict[str, Any]], Awaitable[None]]


def _route_pattern(scope: Scope) -> str:
    """获取请求匹配的路由模板；未匹配（404）时统一为 unmatched，控制标签基数"""
    route = scope.get("route")
    if route is not None:
        return getattr(route, "path", None) or scope.get("path", "unmatched")
    return "unmatched"


class MetricsMiddleware:
    """
    HTTP 指标采集中间件（纯 ASGI，不缓冲流式响应）

    用法（main.py）：
        app.add_middleware(MetricsMiddleware)
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        method = scope.get("method", "")

        # 从 http.response.start 事件捕获实际状态码
        captured = {"status": ""}

        async def send_wrapper(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start" and not captured["status"]:
                captured["status"] = str(message.get("status", ""))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # 响应头已发出后的异常（如 SSE 生成器中途抛错）不再重复计 500，
            # 仅补记未发出响应头即失败的情况
            if not captured["status"]:
                captured["status"] = "500"
            http_requests_total.labels(
                method=method,
                path=_route_pattern(scope),
                status=captured["status"],
            ).inc()
            http_request_duration_seconds.labels(
                method=method, path=_route_pattern(scope)
            ).observe(time.perf_counter() - start)
            raise

        http_requests_total.labels(
            method=method,
            path=_route_pattern(scope),
            status=captured["status"] or "500",
        ).inc()
        http_request_duration_seconds.labels(
            method=method, path=_route_pattern(scope)
        ).observe(time.perf_counter() - start)
