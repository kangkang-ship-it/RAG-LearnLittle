"""
模型工厂模块

提供 Chat / Embedding 模型的统一创建入口。
通过 MODEL_PROVIDER 环境变量一键切换模型提供商，
支持 DASHSCOPE（阿里云百炼）和 OLLAMA（本地）两种提供商。

切换提供商只需修改 .env 中的 MODEL_PROVIDER 值，无需改动任何代码。
"""

import os
from enum import Enum

from app.core.logger_handler import logger


# ============================================================
# 模型提供商枚举
# ============================================================

class ModelProvider(str, Enum):
    """模型提供商"""
    DASHSCOPE = "dashscope"   # 阿里云百炼（云端）
    OLLAMA = "ollama"         # Ollama（本地）


def get_provider() -> ModelProvider:
    """
    获取当前配置的模型提供商

    读取 MODEL_PROVIDER 环境变量（不区分大小写），
    未配置或值非法时默认为 DASHSCOPE。

    Returns:
        ModelProvider 枚举值
    """
    raw = os.getenv("MODEL_PROVIDER", "dashscope").strip().lower()
    try:
        return ModelProvider(raw)
    except ValueError:
        logger.warning(f"未知的 MODEL_PROVIDER: {raw}，回退到 dashscope")
        return ModelProvider.DASHSCOPE


# ============================================================
# 公开工厂函数
# ============================================================

def create_chat_model():
    """
    创建 Chat 模型实例

    根据 MODEL_PROVIDER 环境变量自动选择对应的 Chat 模型。
    - dashscope → ChatTongyi（阿里云百炼）
    - ollama    → ChatOllama（本地）

    Returns:
        LangChain ChatModel 实例
    """
    provider = get_provider()
    logger.info(f"创建 Chat 模型 (provider={provider.value})")

    if provider == ModelProvider.DASHSCOPE:
        return _create_dashscope_chat_model()
    return _create_ollama_chat_model()


def create_embed_model():
    """
    创建 Embedding 模型实例

    根据 MODEL_PROVIDER 环境变量自动选择对应的 Embedding 模型。
    - dashscope → DashScopeEmbeddings（text-embedding-v3）
    - ollama    → OllamaEmbeddings

    注意：切换 Embedding 提供商后需要重建 ChromaDB 中的所有向量。

    Returns:
        LangChain Embeddings 实例
    """
    provider = get_provider()
    logger.info(f"创建 Embedding 模型 (provider={provider.value})")

    if provider == ModelProvider.DASHSCOPE:
        return _create_dashscope_embed_model()
    return _create_ollama_embed_model()


# ============================================================
# DashScope（阿里云百炼）实现
# ============================================================

# DashScope OpenAI 兼容端点
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _create_dashscope_chat_model():
    """
    创建 DashScope Chat 模型（阿里云百炼）

    使用 ChatOpenAI + DashScope 的 OpenAI 兼容端点，
    避免 ChatTongyi 对部分新模型的 URL 构造问题。

    环境变量：
    - DASHSCOPE_API_KEY: API 密钥（必需）
    - DASHSCOPE_CHAT_MODEL: 模型名称（默认 qwen3-max）

    Returns:
        ChatOpenAI 实例（指向 DashScope 兼容端点）
    """
    from langchain_openai import ChatOpenAI

    model_name = os.getenv("DASHSCOPE_CHAT_MODEL", "qwen3-max")
    api_key = os.getenv("DASHSCOPE_API_KEY", "")

    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY 未配置，请在 .env 中设置")

    logger.info(f"DashScope Chat 模型: {model_name} @ {DASHSCOPE_BASE_URL}")

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=DASHSCOPE_BASE_URL,
        streaming=True,
    )

    """
    😄
    """
def _create_dashscope_embed_model():
    """
    创建 DashScope Embedding 模型

    环境变量：
    - DASHSCOPE_API_KEY: API 密钥（必需）
    - DASHSCOPE_EMBED_MODEL: 模型名称（默认 text-embedding-v3）

    Returns:
        DashScopeEmbeddings 实例
    """
    try:
        from langchain_community.embeddings import DashScopeEmbeddings

        model_name = os.getenv("DASHSCOPE_EMBED_MODEL", "text-embedding-v3")
        api_key = os.getenv("DASHSCOPE_API_KEY", "")

        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY 未配置，请在 .env 中设置")

        logger.info(f"DashScope Embedding 模型: {model_name}")

        return DashScopeEmbeddings(
            model=model_name,
            dashscope_api_key=api_key,
        )
    except ImportError:
        logger.error("缺少 dashscope 依赖，请执行: pip install dashscope")
        raise


# ============================================================
# Ollama（本地）实现
# ============================================================

def _create_ollama_chat_model():
    """
    创建 Ollama Chat 模型

    环境变量：
    - OLLAMA_BASE_URL: Ollama 服务地址（默认 http://localhost:11434）
    - OLLAMA_CHAT_MODEL: 模型名称（默认 qwen3:latest）
    - OLLAMA_TIMEOUT: 请求超时秒数（默认 30）

    Returns:
        ChatOllama 实例
    """
    from langchain_ollama import ChatOllama

    model_name = os.getenv("OLLAMA_CHAT_MODEL", "qwen3:latest")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    timeout = int(os.getenv("OLLAMA_TIMEOUT", "30"))

    logger.info(f"Ollama Chat 模型: {model_name} @ {base_url}")

    return ChatOllama(
        model=model_name,
        base_url=base_url,
        timeout=timeout,
        streaming=True,
    )


def _create_ollama_embed_model():
    """
    创建 Ollama Embedding 模型

    环境变量：
    - OLLAMA_BASE_URL: Ollama 服务地址（默认 http://localhost:11434）
    - OLLAMA_EMBED_MODEL: 模型名称（默认 nomic-embed-text）

    Returns:
        OllamaEmbeddings 实例
    """
    from langchain_ollama import OllamaEmbeddings

    model_name = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    logger.info(f"Ollama Embedding 模型: {model_name} @ {base_url}")

    return OllamaEmbeddings(
        model=model_name,
        base_url=base_url,
    )
