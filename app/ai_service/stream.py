"""
流式响应模块

基于 CompiledStateGraph.astream_events(version="v2") 实现逐 token 流式输出。
支持中间件生命周期钩子（before/after agent、before/after tool）。

yield 原始 dict，由调用方负责 SSE 格式化。
"""

import asyncio
import time
from typing import AsyncGenerator, Dict, Any, Optional

from app.ai_service.agent_middleware import default_middleware
from app.core.logger_handler import logger


async def run_agent_stream(
    agent,
    agent_input: Dict[str, Any],
    config: Dict[str, Any],
    timeout: int = 60,
    middleware=None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    执行 Agent 并逐 token 产出事件字典

    Args:
        agent: CompiledStateGraph 实例（由 create_agent 返回）
        agent_input: Agent 输入，格式 {"messages": [...]}
        config: 运行配置，如 {"recursion_limit": max_iter}
        timeout: 超时秒数（默认 60）
        middleware: AgentMiddleware 实例（默认使用 default_middleware）

    Yields:
        事件字典，类型由 type 字段区分：
        - {"type": "response", "content": "..."}   逐 token 内容
        - {"type": "tool_start", "name": "..."}    工具调用开始
        - {"type": "tool_end", "name": "..."}      工具调用完成
        - {"type": "error", "content": "..."}      错误信息
        - {"type": "stream_done", "full_response": "..."} 流式输出完成
    """
    mw = middleware or default_middleware
    accumulated = ""
    tool_start_times: Dict[str, float] = {}

    # 触发 before_agent 钩子
    messages = agent_input.get("messages", [])
    last_msg = messages[-1].content if messages else ""
    await mw.trigger("before_agent", {
        "input": last_msg[:200],
        "message_count": len(messages),
    })

    try:
        async with asyncio.timeout(timeout):
            async for event in agent.astream_events(
                agent_input,
                config=config,
                version="v2",
            ):
                event_type = event["event"]

                # ---- 逐 token 输出 ----
                if event_type == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        accumulated += chunk.content
                        yield {"type": "response", "content": chunk.content}

                # ---- 工具调用开始 ----
                elif event_type == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    tool_start_times[tool_name] = time.time()
                    logger.debug(f"工具调用开始: {tool_name}")
                    await mw.trigger("before_tool", {"tool_name": tool_name})
                    yield {"type": "tool_start", "name": tool_name}

                # ---- 工具调用完成 ----
                elif event_type == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    duration = 0
                    if tool_name in tool_start_times:
                        duration = round(
                            (time.time() - tool_start_times.pop(tool_name)) * 1000
                        )
                    logger.debug(f"工具调用完成: {tool_name} ({duration}ms)")
                    await mw.trigger("after_tool", {
                        "tool_name": tool_name,
                        "duration_ms": duration,
                    })
                    yield {"type": "tool_end", "name": tool_name, "duration_ms": duration}

    except asyncio.TimeoutError:
        logger.warning(f"Agent 响应超时 (timeout={timeout}s)")
        yield {"type": "error", "content": f"AI 响应超时（{timeout}秒），请重试"}
        return
    except Exception as e:
        logger.error(f"Agent 流式输出异常: {type(e).__name__}: {e}", exc_info=True)
        yield {"type": "error", "content": f"生成失败: {str(e)}"}
        return

    # 触发 after_agent 钩子
    await mw.trigger("after_agent", {"output": accumulated})

    # 流式完成事件（用 stream_done 避免与调用方的 done 混淆）
    yield {"type": "stream_done", "full_response": accumulated}
