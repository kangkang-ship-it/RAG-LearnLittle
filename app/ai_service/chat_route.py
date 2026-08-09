"""
对话路由层（P2-1 编排层改造 · 第一步）

把 chat.py generate_stream 的路由决策与事件转发抽取为独立结构：
- ChatRouteContext: 执行上下文（显式化原闭包状态）
- decide_route: 纯函数路由决策（simple/complex → react / plan_execute）
- react_events / plan_events: 各路径事件流（async generator，产出事件字典）

SSE 格式化仍由路由层（chat.py）完成，事件类型与顺序契约零变化：
- ReAct 路径：仅转发 response / error（tool_* 不转发，与改造前一致）
- Plan 路径：转发 plan_* / tool_* / response / error；plan_fallback 后接 ReAct 重跑
- error 事件后终止（上游据此不发 done、不保存回复）

第二步将把本层迁移为 LangGraph StateGraph（事件总线 + 条件边），
本模块的决策与事件流语义将原样保留。
"""

from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, List, Optional

from app.ai_service.agent_runner import execute_agent
from app.ai_service.plan_execute_agent import execute_plan_agent
from app.core.logger_handler import logger


@dataclass
class ChatRouteContext:
    """一次对话请求的执行上下文（原 generate_stream 闭包状态的显式化）"""
    agent_model: Any                      # 执行链路模型（按模态/思考开关路由后的实例）
    user_id: str
    user_message: str
    system_prompt: str                    # 含 RAG 上下文与引用笔记
    compressed_messages: list             # Token 预算压缩后的历史消息
    db_session_factory: Any               # 数据库会话工厂（供工具使用）
    plan_model: Any = None                # Plan 模型（route=plan_execute 时使用）
    classifier_model: Any = None          # 分类器 L2 模型（classify 节点使用）
    note_service: Any = None
    review_service: Any = None
    email_service: Any = None
    ppt_service: Any = None               # PPT 生成服务（§6.4 注入链路）
    attachment_content: list = field(default_factory=list)   # 多模态 content blocks
    attachment_names: Optional[list] = None                  # 附件文件名（Plan 摘要注入）
    react_timeout: int = 60               # ReAct 路径超时（上游传 LLM_STREAM_TIMEOUT）
    plan_timeout: int = 120               # Plan 路径超时（上游传 LLM_STREAM_TIMEOUT * 2）


def decide_route(complexity: str, plan_model_available: bool) -> str:
    """
    路由决策（纯函数）

    Args:
        complexity: 分类结果（simple / complex）
        plan_model_available: Plan 模型是否可用

    Returns:
        "react"（ReAct）或 "plan_execute"（Plan-and-Execute）
    """
    if complexity == "complex" and plan_model_available:
        return "plan_execute"
    return "react"


async def react_events(ctx: ChatRouteContext, timeout: int) -> AsyncGenerator[dict, None]:
    """
    ReAct 路径事件流（简单问题 / Plan 降级共用）

    Yields:
        response / error 事件（error 后终止；stream_done 不转发，与改造前一致）
    """
    async for event in execute_agent(
        chat_model=ctx.agent_model,
        user_id=ctx.user_id,
        user_message=ctx.user_message,
        system_prompt=ctx.system_prompt,
        compressed_messages=ctx.compressed_messages,
        db_session_factory=ctx.db_session_factory,
        note_service=ctx.note_service,
        review_service=ctx.review_service,
        email_service=ctx.email_service,
        ppt_service=ctx.ppt_service,
        timeout=timeout,
        attachment_content=ctx.attachment_content,
    ):
        event_type = event.get("type", "")
        if event_type in ("response", "error"):
            yield event
            if event_type == "error":
                return
        # ★ 简单路径补转发工具事件（§6.3 第 2 段，行为变更提示见设计方案）：
        # 此前连 tool_start/tool_end 都不转发，补上后简单对话中的工具状态
        # （含 generate_ppt_tool 的生成进度）对前端可见
        elif event_type in ("tool_start", "tool_end", "tool_file"):
            yield event
        # ★ 思考过程实时转发（审查 B+C）：深度思考模式下 reasoning_content
        # 作为 thinking 事件推送，前端显示思考进度（消除零反馈等待焦虑）
        elif event_type == "thinking":
            yield event
        # stream_done 等其余事件不转发（与现状一致）


async def plan_events(
    ctx: ChatRouteContext,
    timeout: int,
    fallback_timeout: int = 60,
) -> AsyncGenerator[dict, None]:
    """
    Plan-Execute 路径事件流（含 plan_fallback → ReAct 重跑）

    Args:
        ctx: 路由上下文
        timeout: Plan 执行总超时（上游传 LLM_STREAM_TIMEOUT * 2）
        fallback_timeout: plan_fallback 后 ReAct 重跑的超时

    Yields:
        plan_start / plan_step / plan_step_start / plan_step_end /
        plan_synthesize / plan_complete / tool_start / tool_end / response / error
        （plan_fallback 事件后接 ReAct 重跑事件；error 后终止）
    """
    forwarded = {
        "plan_start", "plan_step", "plan_step_start", "plan_step_end",
        "plan_synthesize", "plan_complete", "tool_start", "tool_end",
        "tool_file",   # ★ 新增：PPT 生成事件（§6.3 第 2 段）
    }
    async for event in execute_plan_agent(
        chat_model=ctx.agent_model,
        plan_model=ctx.plan_model,
        user_id=ctx.user_id,
        user_message=ctx.user_message,
        system_prompt=ctx.system_prompt,
        compressed_messages=ctx.compressed_messages,
        db_session_factory=ctx.db_session_factory,
        note_service=ctx.note_service,
        review_service=ctx.review_service,
        email_service=ctx.email_service,
        ppt_service=ctx.ppt_service,
        timeout=timeout,
        attachment_content=ctx.attachment_content,
        attachment_names=ctx.attachment_names,
    ):
        event_type = event.get("type", "")
        if event_type == "plan_fallback":
            # Plan 失败，降级为 ReAct 重跑
            logger.info(f"Plan 降级: {event.get('reason', '')}")
            yield event
            async for fallback_event in react_events(ctx, timeout=fallback_timeout):
                yield fallback_event
            return
        if event_type in ("response", "error") or event_type in forwarded:
            yield event
            if event_type == "error":
                return
        # stream_done 不转发（与现状一致）


async def collect_events(events: AsyncGenerator[dict, None]) -> tuple:
    """
    事件流收集（供测试/诊断使用）

    Returns:
        (事件列表, 累积文本)
    """
    collected = []
    accumulated = ""
    async for event in events:
        collected.append(event)
        if event.get("type") == "response":
            accumulated += event.get("content", "")
    return collected, accumulated
