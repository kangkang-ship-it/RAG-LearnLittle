"""
流式响应模块

实现 Agent 对话的流式输出：
- 使用 asyncio.Queue 实现思考过程实时推送
- 回答内容按 chunk 模拟流式输出
- SSE (Server-Sent Events) 格式
"""

import asyncio
import json
from typing import AsyncGenerator, Callable, Optional

from app.core.logger_handler import logger


async def get_agent_stream_response(
    agent_executor,
    input_text: str,
    chat_history: Optional[list] = None,
    thinking_callback: Optional[Callable] = None,
    chunk_size: int = 15,
) -> AsyncGenerator[str, None]:
    """
    获取 Agent 的流式响应（SSE 格式）
    
    使用 asyncio.Queue 协调思考过程推送和回答内容输出。
    思考阶段（工具调用等）通过 thinking_callback 实时推送，
    最终回答按 chunk_size 字符分块模拟流式输出。
    
    Args:
        agent_executor: LangChain AgentExecutor 实例
        input_text: 用户输入
        chat_history: 聊天历史消息列表
        thinking_callback: 思考过程回调（用于推送阶段事件）
        chunk_size: 每次输出的字符数
        
    Yields:
        SSE 格式的事件字符串
    """
    # 构建输入
    agent_input = {
        "input": input_text,
    }
    if chat_history:
        agent_input["chat_history"] = chat_history
    
    try:
        # 推送开始事件
        yield _format_sse({"event": "start", "data": ""})
        
        # 执行 Agent
        result = None
        import asyncio
        loop = asyncio.get_event_loop()
        
        # 在线程池中执行同步 Agent 调用
        result = await loop.run_in_executor(
            None,
            lambda: agent_executor.invoke(agent_input)
        )
        
        # 推送中间步骤（思考过程）
        intermediate_steps = result.get("intermediate_steps", [])
        for step in intermediate_steps:
            action, observation = step
            thinking_event = {
                "event": "thinking",
                "data": {
                    "tool": action.tool,
                    "tool_input": str(action.tool_input)[:200],
                    "observation": str(observation)[:200],
                }
            }
            yield _format_sse(thinking_event)
            
            # 同时调用回调
            if thinking_callback:
                try:
                    await thinking_callback(thinking_event)
                except Exception:
                    pass
        
        # 流式输出最终回答
        output = result.get("output", "")
        
        # 按 chunk_size 分块输出
        for i in range(0, len(output), chunk_size):
            chunk = output[i:i + chunk_size]
            yield _format_sse({"event": "token", "data": chunk})
            
            # 模拟流式延迟（可选）
            await asyncio.sleep(0.02)
        
        # 推送完成事件
        yield _format_sse({
            "event": "done",
            "data": {
                "full_response": output,
                "total_tokens": len(output),
            }
        })
        
    except Exception as e:
        logger.error(f"Agent 流式响应异常: {e}")
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
