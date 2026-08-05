"""
Agent 工厂模块

使用工厂模式创建 Agent（基于 LangGraph CompiledStateGraph）：
- 每次调用创建全新实例，避免全局状态污染
- 集成 LangChain create_agent（langchain 1.3+ API）
- 支持系统提示词和工具集
"""

from typing import List, Optional

from app.core.logger_handler import logger
from app.utils.config import get_agent_config


class AgentFactory:
    """
    Agent 工厂

    每次调用 create_agent() 创建全新的 Agent 实例，
    避免多用户并发时的全局状态污染。
    """

    @staticmethod
    def create_agent(
        chat_model,
        tools: list,
        system_prompt: str = "",
        max_iterations: int = 10,
    ):
        """
        创建 Agent 实例

        Args:
            chat_model: LangChain Chat 模型
            tools: Agent 可用的工具列表
            system_prompt: 系统提示词
            max_iterations: 最大迭代次数（递归限制）

        Returns:
            CompiledStateGraph 实例（可通过 astream/ainvoke 调用）
        """
        from langchain.agents import create_agent

        # 构建 Agent（langchain 1.3+ API）
        agent = create_agent(
            model=chat_model,
            tools=tools or [],
            system_prompt=system_prompt or "你是一个智能笔记助手，帮助用户管理知识、检索信息和回答问题。",
        )

        logger.debug(f"Agent 创建完成: tools={len(tools)}, max_iter={max_iterations}")
        return agent, max_iterations
