"""
模型工厂模块

提供 Chat / Embedding / Vision 模型的创建和管理。
内建 Circuit Breaker 状态机，实现 LLM 主备切换：
- Chat 优先本地 Ollama，不可用时自动降级 DashScope
- Embedding 固定使用本地 Ollama（不参与切换）
"""

import os
import time
from enum import Enum
from typing import Optional

from app.core.logger_handler import logger
from app.db.redis_client import get_redis


class CircuitState(str, Enum):
    """熔断器三态"""
    CLOSED = "CLOSED"           # 正常：使用 Ollama
    OPEN = "OPEN"               # 熔断：跳过 Ollama，直接用 DashScope
    HALF_OPEN = "HALF_OPEN"    # 半开：冷却到期，试探 1 次


class CircuitBreaker:
    """
    Circuit Breaker 熔断器
    
    三态状态机：CLOSED → OPEN → HALF_OPEN → CLOSED/OPEN
    
    状态存储在 Redis 中，支持多进程共享。
    """
    
    def __init__(self, user_id: str = "global"):
        """
        初始化熔断器
        
        Args:
            user_id: 用户 ID（支持按用户独立熔断）
        """
        self.user_id = user_id
        self.threshold = int(os.getenv("LLM_CIRCUIT_BREAKER_THRESHOLD", "3"))
        self.cooldown = int(os.getenv("LLM_CIRCUIT_BREAKER_COOLDOWN", "60"))
    
    def _state_key(self) -> str:
        return f"cb:chat:{self.user_id}:state"
    
    def _failures_key(self) -> str:
        return f"cb:chat:{self.user_id}:failures"
    
    async def get_state(self) -> CircuitState:
        """
        获取当前熔断器状态
        
        Returns:
            当前状态（CLOSED / OPEN / HALF_OPEN）
        """
        redis = get_redis()
        state = await redis.get(self._state_key())
        if state is None:
            return CircuitState.CLOSED
        
        if state == CircuitState.OPEN:
            # 检查冷却时间是否到期
            failures_key = self._failures_key()
            ttl = await redis.ttl(failures_key)
            if ttl <= 0:
                # 冷却到期，进入半开状态
                await redis.set(self._state_key(), CircuitState.HALF_OPEN)
                return CircuitState.HALF_OPEN
        
        return CircuitState(state)
    
    async def record_success(self) -> None:
        """
        记录成功调用：重置熔断器到 CLOSED 状态
        """
        redis = get_redis()
        await redis.set(self._state_key(), CircuitState.CLOSED)
        await redis.delete(self._failures_key())
        logger.info(f"Circuit Breaker 重置为 CLOSED (user={self.user_id})")
    
    async def record_failure(self) -> None:
        """
        记录失败调用：累计失败次数，达到阈值则触发熔断
        
        失败计数使用 Redis INCR，TTL 与冷却时间绑定。
        """
        redis = get_redis()
        
        # 累计失败次数
        failures = await redis.incr(self._failures_key())
        if failures == 1:
            await redis.expire(self._failures_key(), self.cooldown)
        
        logger.warning(
            f"Circuit Breaker 失败计数: {failures}/{self.threshold} (user={self.user_id})"
        )
        
        # 达到阈值，触发熔断
        if failures >= self.threshold:
            await redis.set(self._state_key(), CircuitState.OPEN)
            logger.warning(f"Circuit Breaker 触发熔断 → OPEN (user={self.user_id})")
    
    async def should_use_fallback(self) -> bool:
        """
        判断是否应该使用备用模型（DashScope）
        
        Returns:
            True 表示应使用备用模型
        """
        state = await self.get_state()
        return state in (CircuitState.OPEN, CircuitState.HALF_OPEN)


def create_chat_model():
    """
    创建 Chat 模型实例
    
    根据 LLM_STRATEGY 环境变量决定使用哪个模型提供商：
    - OLLAMA_FIRST: 优先 Ollama，不可用时降级 DashScope
    - OLLAMA_ONLY: 仅使用 Ollama
    - ALIYUN_ONLY: 仅使用 DashScope
    
    Returns:
        LangChain ChatModel 实例
    """
    strategy = os.getenv("LLM_STRATEGY", "OLLAMA_FIRST")
    
    if strategy == "ALIYUN_ONLY":
        return _create_dashscope_chat_model()
    
    # 默认使用 Ollama
    return _create_ollama_chat_model()


def create_embed_model():
    """
    创建 Embedding 模型实例
    
    Embedding 不参与主备切换，固定使用 EMBED_PROVIDER 配置的提供商。
    更改此配置后需要重建 ChromaDB 所有向量。
    
    Returns:
        LangChain Embeddings 实例
    """
    provider = os.getenv("EMBED_PROVIDER", "OLLAMA")
    
    if provider == "DASHSCOPE":
        return _create_dashscope_embed_model()
    
    return _create_ollama_embed_model()


def _create_ollama_chat_model():
    """
    创建 Ollama Chat 模型
    
    从环境变量读取模型名称和基础 URL。
    
    Returns:
        ChatOllama 实例
    """
    from langchain_ollama import ChatOllama
    
    model_name = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:latest")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    timeout = int(os.getenv("OLLAMA_TIMEOUT", "30"))
    
    logger.info(f"创建 Ollama Chat 模型: {model_name} @ {base_url}")
    
    return ChatOllama(
        model=model_name,
        base_url=base_url,
        timeout=timeout,
        streaming=True,  # 显式启用流式输出
    )


def _create_dashscope_chat_model():
    """
    创建 DashScope Chat 模型（阿里云百炼）
    
    Returns:
        DashScope ChatModel 实例
    """
    try:
        from langchain_community.chat_models import ChatTongyi
        
        model_name = os.getenv("DASHSCOPE_CHAT_MODEL", "qwen3-max")
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        
        logger.info(f"创建 DashScope Chat 模型: {model_name}")
        
        return ChatTongyi(
            model=model_name,
            dashscope_api_key=api_key,
        )
    except ImportError:
        logger.error("请安装 dashscope: pip install dashscope")
        raise


def _create_ollama_embed_model():
    """
    创建 Ollama Embedding 模型
    
    Returns:
        OllamaEmbeddings 实例
    """
    from langchain_ollama import OllamaEmbeddings
    
    model_name = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    logger.info(f"创建 Ollama Embedding 模型: {model_name} @ {base_url}")
    
    return OllamaEmbeddings(
        model=model_name,
        base_url=base_url,
    )


def _create_dashscope_embed_model():
    """
    创建 DashScope Embedding 模型
    
    Returns:
        DashScope Embeddings 实例
    """
    try:
        from langchain_community.embeddings import DashScopeEmbeddings
        
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        
        logger.info("创建 DashScope Embedding 模型")
        
        return DashScopeEmbeddings(
            model="text-embedding-v3",
            dashscope_api_key=api_key,
        )
    except ImportError:
        logger.error("请安装 dashscope: pip install dashscope")
        raise
