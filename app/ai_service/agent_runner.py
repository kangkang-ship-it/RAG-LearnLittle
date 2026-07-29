"""
Agent 运行器

封装 Agent 创建 + 流式输出的完整调用链路：
- Agent 工厂创建
- 工具集绑定（支持按需加载）
- 输入构造（messages 格式）
- 流式输出（通过 stream.run_agent_stream）
- 中间件集成（before/after agent、before/after tool）
- 超时保护
"""

from typing import AsyncGenerator, Dict, Any, List, Optional

from langchain_core.messages import HumanMessage

from app.ai_service.agent import AgentFactory
from app.ai_service.agent_tools import create_agent_tools
from app.ai_service.stream import run_agent_stream
from app.core.logger_handler import logger
from app.utils.config import get_agent_config, get_tool_routing_config

# 加载工具组
def resolve_tool_groups(user_message: str) -> List[str]:
    """
    根据用户消息关键词匹配，决定需要加载哪些工具组

    路由逻辑：
    1. 从 agent.yaml 加载 tool_routing 配置
    2. 以 default_groups 为起点
    3. 遍历 keyword_rules，命中关键词则追加对应工具组
    4. 去重后返回

    Args:
        user_message: 用户当前消息文本

    Returns:
        工具组名称列表，如 ["base", "note_read", "note_write"]
    """
    routing_config = get_tool_routing_config()
    if not routing_config:
        # 未配置路由规则 → 返回 None 表示全量加载
        return None

    default_groups = routing_config.get("default_groups", ["base", "note_read"])
    keyword_rules = routing_config.get("keyword_rules", {})

    # 以默认组为起点
    selected = list(default_groups)

    # 关键词匹配 → 追加工具组
    for group_name, keywords in keyword_rules.items():
        if group_name in selected:
            continue  # 已在列表中，跳过
        for kw in keywords:
            if kw in user_message:
                selected.append(group_name)
                logger.debug(f"工具路由匹配: 关键词 '{kw}' → 追加工具组 '{group_name}'")
                break  # 命中一个即可，无需继续匹配同组

    logger.info(f"工具路由结果: groups={selected} (message='{user_message[:50]}...')")
    return selected


async def execute_agent(
    chat_model,
    user_id: str,
    user_message: str,
    system_prompt: str,
    compressed_messages: Optional[List] = None,
    db_session_factory=None,
    note_service=None,
    review_service=None,
    timeout: int = 60,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    执行 Agent 并返回事件字典流

    封装完整的 Agent 调用链路：创建 → 构造输入 → 流式输出。

    Args:
        chat_model: LangChain Chat 模型实例
        user_id: 当前用户 ID
        user_message: 用户当前消息
        system_prompt: 系统提示词（含 RAG 上下文）
        compressed_messages: 经过 Token 预算压缩的历史消息列表
        db_session_factory: 数据库会话工厂（供工具使用）
        note_service: 笔记服务实例（供笔记相关工具使用）
        review_service: 回顾服务实例（供回顾相关工具使用）
        timeout: 超时秒数

    Yields:
        事件字典（type 字段区分类型）
    """
    agent_config = get_agent_config()

    # 1. 工具路由：根据用户消息关键词匹配决定加载哪些工具组
    tool_groups = resolve_tool_groups(user_message)

    # 2. 创建工具集（注入笔记服务和回顾服务 + 按需加载）
    tools = create_agent_tools(
        user_id=user_id,
        note_service=note_service,
        review_service=review_service,
        db_session_factory=db_session_factory,
        groups=tool_groups,
    )

    # 3. 创建 Agent
    agent, max_iter = AgentFactory.create_agent(
        chat_model=chat_model,
        tools=tools,
        system_prompt=system_prompt,
        max_iterations=agent_config.get("max_iterations", 5),
    )

    # 4. 构造 Agent 输入（messages 格式）
    messages = list(compressed_messages or [])
    messages.append(HumanMessage(content=user_message))
    agent_input = {"messages": messages}

    # 5. 流式输出（内含中间件钩子 + 超时保护 + 循环检测）
    # recursion_limit 计算每个节点执行（LLM调用 + 工具执行），而非循环次数
    # 每次迭代约 2-3 步，乘以 3 留出安全余量
    recursion_limit = max_iter * 3
    max_consecutive_tool_calls = agent_config.get("max_consecutive_tool_calls", 6)
    async for event in run_agent_stream(
        agent=agent,
        agent_input=agent_input,
        config={"recursion_limit": recursion_limit},
        timeout=timeout,
        max_consecutive_tool_calls=max_consecutive_tool_calls,
    ):
        yield event
