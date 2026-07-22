"""
流式响应模块

实现 Agent 对话的真正异步流式输出：
- 使用 AgentExecutor.astream() 进行异步流式调用
- 支持 chat_history 上下文注入
- SSE (Server-Sent Events) 格式推送
"""

import asyncio
import json
from typing import AsyncGenerator, Optional, List

from app.core.logger_handler import logger


async def get_agent_stream_response(
    agent_executor,
    input_text: str,
    chat_history: Optional[list] = None,
    chunk_size: int = 15,
) -> AsyncGenerator[str, None]:
    """
    获取 Agent 的异步流式响应（SSE 格式）

    使用 AgentExecutor.astream() 实现真正的异步流式调用，
    支持 chat_history 上下文注入。

    Args:
        agent_executor: LangChain AgentExecutor 实例
        input_text: 用户输入
        chat_history: 聊天历史消息列表（LangChain Message 格式）
        chunk_size: 输出分块大小（字符数）

    Yields:
        SSE 格式的事件字符串
    """
    # 构建 Agent 输入
    agent_input = {
        "input": input_text,
    }
    if chat_history:
        agent_input["chat_history"] = chat_history

    try:
        # 推送开始事件
        yield _format_sse({"event": "start", "data": ""})

        accumulated = ""

        # 使用 AgentExecutor.astream() 进行异步流式调用
        async for chunk in agent_executor.astream(
            agent_input,
            {"return_only_outputs": True},
        ):
            output = chunk.get("output", "")
            if output:
                # 计算新增内容
                new_text = output[len(accumulated):]
                accumulated = output

                if new_text:
                    # 按 chunk_size 分块推送
                    for i in range(0, len(new_text), chunk_size):
                        text_chunk = new_text[i:i + chunk_size]
                        yield _format_sse({"event": "token", "data": text_chunk})

        # 推送完成事件
        yield _format_sse({
            "event": "done",
            "data": {
                "full_response": accumulated,
                "total_tokens": len(accumulated),
            }
        })

    except asyncio.TimeoutError:
        logger.error("Agent 流式响应超时")
        yield _format_sse({
            "event": "error",
            "data": {"message": "响应超时，请重试"}
        })
    except Exception as e:
        logger.error(f"Agent 流式响应异常: {e}", exc_info=True)
        yield _format_sse({
            "event": "error",
            "data": {"message": str(e)}
        })


def _format_sse(event: dict) -> str:
    """
    格式化为 SSE (Server-Sent Events) 格式

    格式：
    event: <event_type>
    data: <json_data>

    Args:
        event: 事件字典，包含 event 和 data 字段

    Returns:
        SSE 格式字符串
    """
    event_type = event.get("event", "message")
    data = event.get("data", "")

    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False)

    return f"event: {event_type}\ndata: {data}\n\n"
