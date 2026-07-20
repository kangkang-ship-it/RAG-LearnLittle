"""
Agent 工厂模块

使用工厂模式创建 AgentExecutor 实例：
- 每次调用创建全新实例，避免全局状态污染
- 集成 LangChain create_tool_calling_agent
- 支持最大迭代次数限制
- 通过 ContextVar 传递用户上下文
"""

import os
from typing import List, Optional

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.core.logger_handler import logger
from app.utils.config import get_agent_config


class AgentFactory:
    """
    Agent 工厂
    
    每次调用 create_agent() 创建全新的 AgentExecutor 实例，
    避免多用户并发时的全局状态污染。
    """
    
    @staticmethod
    def create_agent(
        chat_model,
        tools: list,
        system_prompt: str = "",
        max_iterations: int = 5,
    ):
        """
        创建 AgentExecutor 实例
        
        Args:
            chat_model: LangChain Chat 模型
            tools: Agent 可用的工具列表
            system_prompt: 系统提示词
            max_iterations: 最大迭代次数
            
        Returns:
            AgentExecutor 实例
        """
        from langchain.agents import AgentExecutor, create_tool_calling_agent
        
        # 构建 Prompt 模板
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt or "你是一个智能笔记助手，帮助用户管理知识、检索信息和回答问题。"),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        # 创建 Agent
        agent = create_tool_calling_agent(
            llm=chat_model,
            tools=tools,
            prompt=prompt,
        )
        
        # 包装为 AgentExecutor
        executor = AgentExecutor(
            agent=agent,
            tools=tools,
            max_iterations=max_iterations,
            verbose=False,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )
        
        logger.debug(f"Agent 创建完成: tools={len(tools)}, max_iter={max_iterations}")
        return executor
