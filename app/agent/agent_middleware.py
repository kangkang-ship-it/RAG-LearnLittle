"""
Agent 中间件模块

基于 LangGraph 的 Agent 生命周期钩子：
- before_agent / after_agent
- before_model / after_model
- 用于日志记录、性能监控等
"""

from typing import Any, Callable, Dict, Optional

from app.core.logger_handler import logger


class AgentMiddleware:
    """
    Agent 中间件
    
    提供 Agent 执行生命周期的钩子，用于：
    - 日志记录（模型调用、工具调用）
    - 性能监控（耗时统计）
    - 调试辅助
    """
    
    def __init__(self):
        """初始化中间件"""
        self._hooks: Dict[str, list] = {
            "before_agent": [],
            "after_agent": [],
            "before_model": [],
            "after_model": [],
            "before_tool": [],
            "after_tool": [],
        }
    
    def register_hook(self, event: str, callback: Callable) -> None:
        """
        注册生命周期钩子
        
        Args:
            event: 事件名称（before_agent/after_agent/before_model/after_model 等）
            callback: 回调函数
        """
        if event in self._hooks:
            self._hooks[event].append(callback)
    
    async def trigger(self, event: str, context: Dict[str, Any]) -> None:
        """
        触发指定事件的所有钩子
        
        Args:
            event: 事件名称
            context: 上下文信息
        """
        for callback in self._hooks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(context)
                else:
                    callback(context)
            except Exception as e:
                logger.error(f"Agent 中间件钩子执行失败 [{event}]: {e}")


# 默认中间件实例（带日志记录）
default_middleware = AgentMiddleware()


async def _log_before_agent(context: dict) -> None:
    """Agent 执行前日志"""
    logger.info(f"Agent 开始执行: input={context.get('input', '')[:100]}...")


async def _log_after_agent(context: dict) -> None:
    """Agent 执行后日志"""
    output = context.get("output", "")
    logger.info(f"Agent 执行完成: output_length={len(output)}")


async def _log_before_model(context: dict) -> None:
    """模型调用前日志"""
    logger.debug(f"调用模型: {context.get('model_name', 'unknown')}")


async def _log_after_model(context: dict) -> None:
    """模型调用后日志"""
    logger.debug(
        f"模型返回: tokens={context.get('token_count', 0)}, "
        f"duration_ms={context.get('duration_ms', 0)}"
    )


# 注册默认日志钩子
import asyncio

default_middleware.register_hook("before_agent", _log_before_agent)
default_middleware.register_hook("after_agent", _log_after_agent)
default_middleware.register_hook("before_model", _log_before_model)
default_middleware.register_hook("after_model", _log_after_model)
