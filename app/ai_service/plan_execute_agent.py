"""
Plan-and-Execute Agent 执行引擎

三阶段状态机：
- Phase 1: Plan（轻量模型生成执行计划）
- Phase 2: Execute（逐步执行，每步用 ReAct Agent）
- Phase 3: Synthesize（汇总结果，生成最终回答）

通过 SSE 事件流推送计划进度和中间结果给前端。
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncGenerator, Dict, Any, List, Optional

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.core.logger_handler import logger
from app.utils.config import get_plan_execute_config, get_tool_groups_config


# ============================================================
# 数据结构
# ============================================================

@dataclass
class PlanStep:
    """执行计划步骤"""
    step: int
    action: str
    tool: str  # 工具名或 "none"
    depends_on: List[int] = field(default_factory=list)
    result: str = ""  # 执行后填充


@dataclass
class ExecutionPlan:
    """执行计划"""
    goal: str
    steps: List[PlanStep]


# ============================================================
# Phase 1: Plan（规划阶段）
# ============================================================

async def _generate_plan(
    plan_model,
    user_message: str,
    system_prompt: str,
    attachment_names: Optional[List[str]] = None,
) -> ExecutionPlan:
    """
    使用轻量模型生成执行计划

    plan_model 为文本模型（无多模态能力），附件只以摘要文本注入，
    使模型感知附件存在、能制定正确计划（设计方案 §6.4）。

    Args:
        plan_model: 轻量 Chat 模型
        user_message: 用户消息
        system_prompt: 系统提示词（含 RAG 上下文）
        attachment_names: 附件文件名列表（无多模态能力的 plan_model 感知附件）

    Returns:
        ExecutionPlan 实例

    Raises:
        ValueError: JSON 解析失败时抛出（调用方负责降级）
    """
    from app.utils.prompt_loader import load_prompt

    prompt_template = load_prompt("plan_generation")
    prompt = prompt_template.replace("{current_time}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    prompt = prompt.replace("{user_message}", user_message[:1000])

    # 注入附件摘要（plan_model 无法看图，但需知道附件存在以制定正确计划）
    if attachment_names:
        prompt += (
            f"\n用户本次请求附带了 {len(attachment_names)} 个附件："
            f"{', '.join(attachment_names[:5])}。"
            "请将这些附件作为任务的一部分制定计划（附件内容将由执行阶段的多模态模型处理）。"
        )

    config = get_plan_execute_config()
    plan_timeout = config.get("plan_timeout", 10)

    try:
        async with asyncio.timeout(plan_timeout):
            response = await plan_model.ainvoke([HumanMessage(content=prompt)])
            content = response.content.strip()
    except asyncio.TimeoutError:
        logger.warning(f"Plan 生成超时 ({plan_timeout}s)")
        raise ValueError("Plan 生成超时")

    # 解析 JSON（兼容 markdown code block）
    content = re.sub(r"```json\s*", "", content)
    content = re.sub(r"```\s*", "", content)
    content = content.strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"Plan JSON 解析失败: {e}, raw={content[:300]}")
        raise ValueError(f"Plan JSON 解析失败: {e}")

    goal = data.get("goal", user_message[:50])
    raw_steps = data.get("steps", [])

    if not raw_steps:
        raise ValueError("Plan 无步骤")

    # 限制最大步骤数
    max_steps = config.get("max_steps", 5)
    raw_steps = raw_steps[:max_steps]

    steps = []
    for s in raw_steps:
        steps.append(PlanStep(
            step=s.get("step", len(steps) + 1),
            action=s.get("action", ""),
            tool=s.get("tool", "none"),
            depends_on=s.get("depends_on", []),
        ))

    plan = ExecutionPlan(goal=goal, steps=steps)
    logger.info(f"Plan 生成完成: goal={goal}, steps={len(steps)}")
    return plan


# ============================================================
# Phase 2: Execute（执行阶段）
# ============================================================

def _topological_batches(steps: List[PlanStep]) -> List[List[PlanStep]]:
    """
    拓扑排序，将无依赖的步骤分组为批次（可并行执行）

    Returns:
        批次列表，每个批次内的步骤可并行执行
    """
    completed = set()
    remaining = list(steps)
    batches = []

    while remaining:
        # 找到所有依赖已完成的步骤
        batch = [
            s for s in remaining
            if all(d in completed for d in s.depends_on)
        ]
        if not batch:
            # 存在循环依赖，强制顺序执行剩余步骤
            logger.warning("检测到循环依赖，强制顺序执行剩余步骤")
            batch = remaining

        batches.append(batch)
        for s in batch:
            completed.add(s.step)
            remaining.remove(s)

    return batches


def _resolve_step_tool_groups(step: PlanStep) -> Optional[List[str]]:
    """
    根据步骤的 tool 字段反查所属工具组

    从 agent.yaml 的 tool_groups 配置构建 工具名 → 组名 反向映射，
    根据 step.tool 查找其所属的工具组。
    始终包含 "base" 组（基础工具）。

    Args:
        step: 执行计划步骤

    Returns:
        工具组列表，如 ["base", "note_write"]；tool 为 "none" 时返回 None
    """
    if not step.tool or step.tool == "none":
        return None

    # 注意：tool_groups 定义在 agent.yaml 顶层（get_tool_groups_config），
    # 不能使用 get_agent_config()（只返回 "agent:" 段），否则映射永远为空。
    tool_groups_config = get_tool_groups_config()

    # 构建反向映射：工具名 → 组名
    tool_to_group = {}
    for group_name, tools in tool_groups_config.items():
        for tool_name in tools:
            tool_to_group[tool_name] = group_name

    # 查找 step.tool 所属的组
    matched_groups = ["base"]  # 始终包含基础组
    group = tool_to_group.get(step.tool)
    if group is None:
        # 工具名未匹配到任何组（如模型输出了未知工具名）→ 回退关键词路由，
        # 由 execute_agent 按 default_groups（全量）加载，避免步骤无工具可用
        logger.warning(f"步骤 {step.step} 工具 '{step.tool}' 未匹配到任何工具组，回退关键词路由（全量组）")
        return None
    elif group != "base" and group not in matched_groups:
        matched_groups.append(group)
        logger.debug(f"步骤 {step.step} 工具路由: tool='{step.tool}' → 工具组 {matched_groups}")

    return matched_groups


async def _execute_step(
    step: PlanStep,
    chat_model,
    user_id: str,
    user_message: str,
    system_prompt: str,
    compressed_messages: list,
    db_session_factory,
    note_service,
    review_service,
    email_service,
    step_timeout: int,
    previous_results: Dict[int, str],
    attachment_content: Optional[List[dict]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    执行单个计划步骤

    如果步骤需要工具调用 → 创建专用 ReAct Agent（prompt 限定在当前步骤）
    如果不需要工具 → 直接 LLM 流式生成

    Args:
        attachment_content: 附件多模态 content blocks（透传给执行 Agent / 无工具 LLM 路径）
    """
    yield {"type": "plan_step_start", "step": step.step, "action": step.action}

    # 构建步骤专用上下文
    step_context_parts = [f"当前任务步骤：{step.action}"]

    # 注入前置步骤结果
    if step.depends_on:
        for dep_id in step.depends_on:
            if dep_id in previous_results:
                step_context_parts.append(
                    f"步骤 {dep_id} 的结果：{previous_results[dep_id][:500]}"
                )

    step_context = "\n".join(step_context_parts)
    step_system_prompt = system_prompt + f"\n\n---\n当前执行步骤上下文：\n{step_context}"

    if step.tool and step.tool != "none":
        # 需要工具调用 → 使用 ReAct Agent
        try:
            from app.ai_service.agent_runner import execute_agent

            # 根据 step.tool 反查工具组，跳过关键词路由
            step_tool_groups = _resolve_step_tool_groups(step)

            accumulated = ""
            async for event in execute_agent(
                chat_model=chat_model,
                user_id=user_id,
                user_message=f"{user_message}\n\n请重点完成：{step.action}",
                system_prompt=step_system_prompt,
                compressed_messages=compressed_messages,
                db_session_factory=db_session_factory,
                note_service=note_service,
                review_service=review_service,
                email_service=email_service,
                timeout=step_timeout,
                override_groups=step_tool_groups,
                attachment_content=attachment_content,
            ):
                event_type = event.get("type", "")
                if event_type == "response":
                    accumulated += event.get("content", "")
                elif event_type == "error":
                    yield event
                    step.result = f"步骤 {step.step} 执行出错"
                    return
                # 透传所有事件（response / tool_start / tool_end / thinking）
                yield event

            step.result = accumulated[:500] if accumulated else f"步骤 {step.step} 完成"

        except Exception as e:
            logger.error(f"步骤 {step.step} 执行失败: {e}")
            step.result = f"步骤 {step.step} 执行失败: {str(e)}"
            yield {"type": "response", "content": f"\n[步骤 {step.step} 执行异常: {str(e)}]\n"}
    else:
        # 不需要工具 → 直接 LLM 流式生成（替代原来的 ainvoke 一次性输出）
        try:
            messages = list(compressed_messages or [])
            if attachment_content:
                content = [{
                    "type": "text",
                    "text": f"{user_message}\n\n请完成以下步骤：{step.action}",
                }]
                content.extend(attachment_content)
                messages.append(HumanMessage(content=content))
            else:
                messages.append(HumanMessage(
                    content=f"{user_message}\n\n请完成以下步骤：{step.action}"
                ))

            accumulated = ""
            async with asyncio.timeout(step_timeout):
                async for chunk in chat_model.astream(messages):
                    if hasattr(chunk, "content") and chunk.content:
                        accumulated += chunk.content
                        yield {"type": "response", "content": chunk.content}

            step.result = accumulated[:500] if accumulated else f"步骤 {step.step} 完成"

        except asyncio.TimeoutError:
            step.result = f"步骤 {step.step} 超时"
            yield {"type": "response", "content": f"\n[步骤 {step.step} 超时]\n"}
        except Exception as e:
            step.result = f"步骤 {step.step} 失败: {str(e)}"
            yield {"type": "response", "content": f"\n[步骤 {step.step} 异常: {str(e)}]\n"}

    yield {"type": "plan_step_end", "step": step.step, "result": step.result[:200]}


async def _execute_batch(
    batch: List[PlanStep],
    chat_model,
    user_id: str,
    user_message: str,
    system_prompt: str,
    compressed_messages: list,
    db_session_factory,
    note_service,
    review_service,
    email_service,
    config: dict,
    previous_results: Dict[int, str],
    attachment_content: Optional[List[dict]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    执行一个批次（批次内步骤无依赖，可并行）

    并行模式使用 asyncio.Queue 实时转发事件，确保前端能即时收到每个步骤的 token。
    """
    enable_parallel = config.get("enable_parallel", True)
    step_timeout = config.get("step_timeout", 30)

    if enable_parallel and len(batch) > 1:
        # 并行执行（asyncio.Queue 实时多路复用）
        max_parallel = config.get("max_parallel_steps", 3)
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = "DONE"

        async def _consume_step(step: PlanStep):
            """消费单个步骤的生成器，将事件放入队列"""
            try:
                async for event in _execute_step(
                    step, chat_model, user_id, user_message, system_prompt,
                    compressed_messages, db_session_factory, note_service,
                    review_service, email_service, step_timeout, previous_results,
                    attachment_content=attachment_content,
                ):
                    await queue.put(event)
            except Exception as e:
                logger.error(f"并行步骤 {step.step} 异常: {e}")
                await queue.put({"type": "error", "content": f"步骤 {step.step} 异常: {e}"})
            finally:
                previous_results[step.step] = step.result
                await queue.put(_SENTINEL)

        for i in range(0, len(batch), max_parallel):
            sub_batch = batch[i:i + max_parallel]
            tasks = [asyncio.create_task(_consume_step(step)) for step in sub_batch]

            # 实时从队列读取事件，直到所有步骤完成
            completed_count = 0
            while completed_count < len(tasks):
                item = await queue.get()
                if item is _SENTINEL:
                    completed_count += 1
                else:
                    yield item

            # 确保所有任务完成
            await asyncio.gather(*tasks, return_exceptions=True)
    else:
        # 顺序执行
        for step in batch:
            async for event in _execute_step(
                step, chat_model, user_id, user_message, system_prompt,
                compressed_messages, db_session_factory, note_service,
                review_service, email_service, step_timeout, previous_results,
                attachment_content=attachment_content,
            ):
                yield event
            previous_results[step.step] = step.result


# ============================================================
# Phase 3: Synthesize（综合阶段）
# ============================================================

async def _synthesize(
    chat_model,
    plan: ExecutionPlan,
    results: Dict[int, str],
    user_message: str,
    system_prompt: str,
    config: dict,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    汇总所有步骤结果，生成最终回答
    """
    yield {"type": "plan_synthesize", "content": "正在汇总结果..."}

    from app.utils.prompt_loader import load_prompt

    synthesize_timeout = config.get("synthesize_timeout", 30)

    # 构建步骤结果摘要
    plan_summary = plan.goal
    step_results_parts = []
    for step in plan.steps:
        result_text = results.get(step.step, "无结果")
        step_results_parts.append(f"步骤 {step.step}（{step.action}）：{result_text[:300]}")
    step_results_text = "\n\n".join(step_results_parts)

    prompt_template = load_prompt("plan_synthesize")
    prompt = prompt_template.replace("{user_message}", user_message[:500])
    prompt = prompt.replace("{plan_summary}", plan_summary)
    prompt = prompt.replace("{step_results}", step_results_text)

    try:
        async with asyncio.timeout(synthesize_timeout):
            # 使用流式输出
            messages = [
                SystemMessage(content=system_prompt[:2000]),
                HumanMessage(content=prompt),
            ]

            accumulated = ""
            async for chunk in chat_model.astream(messages):
                if hasattr(chunk, "content") and chunk.content:
                    accumulated += chunk.content
                    yield {"type": "response", "content": chunk.content}

    except asyncio.TimeoutError:
        logger.warning(f"Synthesize 阶段超时 ({synthesize_timeout}s)")
        yield {"type": "response", "content": "\n\n[结果汇总超时，以上为已完成步骤的部分结果]"}
    except Exception as e:
        logger.error(f"Synthesize 阶段失败: {e}")
        yield {"type": "response", "content": f"\n\n[结果汇总失败: {str(e)}]"}


# ============================================================
# 主入口：execute_plan_agent
# ============================================================

async def execute_plan_agent(
    chat_model,
    plan_model,
    user_id: str,
    user_message: str,
    system_prompt: str,
    compressed_messages: Optional[list] = None,
    db_session_factory=None,
    note_service=None,
    review_service=None,
    email_service=None,
    timeout: int = 120,
    attachment_content: Optional[List[dict]] = None,
    attachment_names: Optional[List[str]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Plan-and-Execute Agent 执行器

    三阶段：Plan → Execute → Synthesize

    Args:
        chat_model: 主模型（用于 Execute + Synthesize）
        plan_model: 轻量模型（用于 Plan）
        user_id: 用户 ID
        user_message: 用户消息
        system_prompt: 系统提示词（含 RAG 上下文）
        compressed_messages: 压缩后的历史消息
        db_session_factory: 数据库会话工厂
        note_service: 笔记服务实例
        review_service: 回顾服务实例
        email_service: 邮件发送服务实例（供 send_email 工具使用）
        timeout: 总超时秒数
        attachment_content: 附件多模态 content blocks（执行阶段透传）
        attachment_names: 附件文件名列表（plan_model 无多模态能力，以摘要注入）

    Yields:
        SSE 事件字典
    """
    config = get_plan_execute_config()
    total_timeout = config.get("total_timeout", timeout)

    # 仅发附件（空消息）时提供兜底文本，避免 plan/synthesize 提示词空洞
    effective_message = user_message.strip() or "请分析我发送的附件"

    try:
        async with asyncio.timeout(total_timeout):
            # ===== Phase 1: Plan =====
            try:
                plan = await _generate_plan(
                    plan_model, effective_message, system_prompt,
                    attachment_names=attachment_names,
                )
            except (ValueError, Exception) as e:
                # Plan 生成失败 → 降级为 ReAct
                logger.warning(f"Plan 生成失败，降级为 ReAct: {e}")
                yield {
                    "type": "plan_fallback",
                    "reason": str(e),
                }
                return

            # 推送计划事件
            yield {
                "type": "plan_start",
                "goal": plan.goal,
                "total_steps": len(plan.steps),
            }
            for step in plan.steps:
                yield {
                    "type": "plan_step",
                    "step": step.step,
                    "action": step.action,
                    "status": "pending",
                }

            # ===== Phase 2: Execute ===== 
            previous_results: Dict[int, str] = {}      # 记录已完成步骤的结果
            batches = _topological_batches(plan.steps) # 拓扑排序批次

            completed_steps = 0
            for batch in batches:               # 逐批执行
                async for event in _execute_batch(             # 异步执行批次
                    batch=batch,
                    chat_model=chat_model,
                    user_id=user_id,
                    user_message=effective_message,
                    system_prompt=system_prompt,
                    compressed_messages=compressed_messages,   # 压缩后历史消息
                    db_session_factory=db_session_factory,     # 数据库会话工厂
                    note_service=note_service,                 # 笔记服务实例
                    review_service=review_service,             # 回顾服务实例
                    email_service=email_service,               # 邮件发送服务实例
                    config=config,                             # 配置字典
                    previous_results=previous_results,         # 已完成步骤结果
                    attachment_content=attachment_content,     # 附件多模态 blocks
                ):
                    yield event
                    if event.get("type") == "plan_step_end":
                        completed_steps += 1

            # ===== Phase 3: Synthesize =====    汇总结果
            async for event in _synthesize(
                chat_model=chat_model,
                plan=plan,
                results=previous_results,
                user_message=effective_message,
                system_prompt=system_prompt,
                config=config,
            ):
                yield event

            # 完成事件
            yield {
                "type": "plan_complete",
                "total_steps": len(plan.steps),
                "completed_steps": completed_steps,
            }

    except asyncio.TimeoutError:
        logger.warning(f"Plan-and-Execute 总超时 ({total_timeout}s)")
        yield {"type": "error", "content": f"复杂任务执行超时（{total_timeout}秒），请简化请求后重试"}
    except Exception as e:
        logger.error(f"Plan-and-Execute 执行异常: {type(e).__name__}: {e}", exc_info=True)
        yield {"type": "error", "content": f"执行失败: {str(e)}"}
