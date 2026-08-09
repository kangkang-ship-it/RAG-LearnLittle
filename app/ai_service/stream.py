"""
流式响应模块

基于 CompiledStateGraph.astream_events(version="v2") 实现逐 token 流式输出。
支持中间件生命周期钩子（before/after agent、before/after tool）。

yield 原始 dict，由调用方负责 SSE 格式化。
"""

import asyncio
import json
import time
from typing import AsyncGenerator, Dict, Any, Optional

from app.ai_service.agent_middleware import default_middleware
from app.core.logger_handler import logger


def _safe_str(value: Any, max_len: int = 500) -> str:
    """事件 payload 转字符串（dict 序列化 + 截断），供审计/钩子上下文使用"""
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            value = str(value)
    return value[:max_len]


def parse_tool_file_event(tool_name: str, tool_output: Any) -> Optional[Dict[str, Any]]:
    """
    检测 PPT / TTS 工具输出，构造 tool_file 事件（设计方案 §6.3 第 1 段）

    支持的工具：
    - generate_ppt_tool → file_id / download_url / title / slide_count
    - text_to_speech   → file_id / audio_url / duration_estimate

    Args:
        tool_name: 工具名
        tool_output: on_tool_end 的 data.output（工具返回值）

    Returns:
        {"type": "tool_file", "name": tool_name, **file_info}；
        工具名不匹配 / 输出非 JSON / 无 file_id → None（跳过）

    v1.6 修复：langgraph 1.x 的 on_tool_end data.output 是 **ToolMessage 对象**
    而非原始字符串（内容在 .content），需先提取再解析——
    否则 tool_file 事件永不产出（前端收不到下载卡片）。
    """
    if tool_name not in ("generate_ppt_tool", "text_to_speech") or not tool_output:
        return None
    try:
        # ToolMessage → 提取 content（工具返回的原始字符串）
        if hasattr(tool_output, "content"):
            tool_output = tool_output.content
        file_info = json.loads(tool_output) if isinstance(tool_output, str) else tool_output
        if isinstance(file_info, dict) and "file_id" in file_info:
            return {"type": "tool_file", "name": tool_name, **file_info}
    except (json.JSONDecodeError, TypeError, ValueError):
        pass  # 工具返回了错误提示（非 JSON），跳过，LLM 会在文本里说明
    return None


async def run_agent_stream(
    agent,
    agent_input: Dict[str, Any],
    config: Dict[str, Any],
    timeout: int = 60,
    middleware=None,
    max_consecutive_tool_calls: int = 6,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    执行 Agent 并逐 token 产出事件字典

    Args:
        agent: CompiledStateGraph 实例（由 create_agent 返回）
        agent_input: Agent 输入，格式 {"messages": [...]}
        config: 运行配置，如 {"recursion_limit": max_iter}
        timeout: 超时秒数（默认 60）
        middleware: AgentMiddleware 实例（默认使用 default_middleware）
        max_consecutive_tool_calls: 连续工具调用上限（无 response 产出时强制终止）

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
    consecutive_tool_calls = 0  # 连续工具调用计数（无 response 产出时递增）

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
                        consecutive_tool_calls = 0  # 有文本产出，重置计数
                        yield {"type": "response", "content": chunk.content}

                # ---- 工具调用开始 ----
                elif event_type == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    consecutive_tool_calls += 1
                    # 循环检测：连续工具调用超过上限且无任何文本产出
                    if consecutive_tool_calls > max_consecutive_tool_calls:
                        logger.warning(
                            f"Agent 循环检测: 连续 {consecutive_tool_calls} 次工具调用无回复，强制终止"
                        )
                        yield {
                            "type": "error",
                            "content": "抱歉，我在处理这个问题时遇到了困难（工具调用循环），请尝试换一种方式提问。",
                        }
                        return
                    tool_start_times[tool_name] = time.time()
                    logger.debug(f"工具调用开始: {tool_name} (连续第{consecutive_tool_calls}次)")
                    await mw.trigger("before_tool", {
                        "tool_name": tool_name,
                        # 工具入参（截断，供工具审计 P2-3）
                        "input": _safe_str(event["data"].get("input")),
                    })
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
                        # 工具结果（截断，供工具审计 P2-3）
                        "output": _safe_str(event["data"].get("output")),
                        "success": True,
                    })
                    yield {"type": "tool_end", "name": tool_name, "duration_ms": duration}

                    # ★ PPT 工具输出检测（§6.3 第 1 段）：额外产出 tool_file 事件
                    # 工具返回的 JSON（file_id/download_url/slide_count/title）直通前端
                    tool_file = parse_tool_file_event(
                        tool_name, event["data"].get("output"))
                    if tool_file:
                        yield tool_file

                # ---- 工具调用失败 ----
                elif event_type == "on_tool_error":
                    tool_name = event.get("name", "unknown")
                    duration = 0
                    if tool_name in tool_start_times:
                        duration = round(
                            (time.time() - tool_start_times.pop(tool_name)) * 1000
                        )
                    logger.warning(f"工具调用失败: {tool_name} ({duration}ms)")
                    await mw.trigger("after_tool", {
                        "tool_name": tool_name,
                        "duration_ms": duration,
                        "output": _safe_str(event["data"].get("error")),
                        "success": False,
                    })
                    yield {
                        "type": "tool_end",
                        "name": tool_name,
                        "duration_ms": duration,
                        "error": True,
                    }

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
