"""
模型工厂模块

提供 Chat / Embedding 模型的统一创建入口。
通过 MODEL_PROVIDER 环境变量一键切换模型提供商，
支持 DASHSCOPE（阿里云百炼）和 OLLAMA（本地）两种提供商。

切换提供商只需修改 .env 中的 MODEL_PROVIDER 值，无需改动任何代码。
"""

import os
from enum import Enum
from typing import Optional

import httpx

from app.core.logger_handler import logger


# ============================================================
# 共享 HTTP 客户端（Chat 模型连接池复用）
# ============================================================

_shared_async_client: Optional[httpx.AsyncClient] = None


def get_shared_async_client() -> httpx.AsyncClient:
    """
    获取模块级共享的 httpx.AsyncClient 实例

    用于 ChatOpenAI 的 http_async_client 参数，实现 TCP/TLS 连接复用。
    首次调用时创建，后续调用返回同一实例。

    Returns:
        httpx.AsyncClient 实例
    """
    global _shared_async_client
    if _shared_async_client is None or _shared_async_client.is_closed:
        _shared_async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=120.0,   # 总超时（流式响应需要较长）
                connect=5.0,     # 连接超时
            ),
            limits=httpx.Limits(
                max_keepalive_connections=20,  # 保持 20 个空闲连接
                max_connections=100,           # 最大 100 个并发连接
                keepalive_expiry=60,           # 空闲连接 60 秒后回收
            ),
            transport=httpx.AsyncHTTPTransport(retries=1),
        )
        logger.debug("共享 httpx.AsyncClient 已创建")
    return _shared_async_client


async def close_shared_http_client():
    """
    关闭共享的 httpx.AsyncClient（在应用 shutdown 时调用）
    """
    global _shared_async_client
    if _shared_async_client is not None and not _shared_async_client.is_closed:
        await _shared_async_client.aclose()
        _shared_async_client = None
        logger.debug("共享 httpx.AsyncClient 已关闭")


# ============================================================
# 模型提供商枚举
# ============================================================

class ModelProvider(str, Enum):
    """模型提供商"""
    DASHSCOPE = "dashscope"   # 阿里云百炼（云端）
    OLLAMA = "ollama"         # Ollama（本地）


def _env_bool(name: str, default: bool = False) -> bool:
    """
    读取布尔型环境变量（true/1/yes → True，其余为 default）

    Args:
        name: 环境变量名
        default: 未设置时的默认值

    Returns:
        布尔值
    """
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes")


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

def create_chat_model(enable_thinking: bool = False):
    """
    创建 Chat 模型实例

    根据 MODEL_PROVIDER 环境变量自动选择对应的 Chat 模型。
    - dashscope → ChatOpenAI（阿里云百炼兼容端点）
    - ollama    → ChatOllama（本地）

    Args:
        enable_thinking: 是否开启思考模式（qwen3 系列支持，DashScope 生效）。
            True 时回答质量更高但延迟大幅增加（长任务可能超时）；
            False 时响应更快。默认关闭，由前端"深度思考"开关控制。

    Returns:
        LangChain ChatModel 实例
    """
    provider = get_provider()
    logger.info(f"创建 Chat 模型 (provider={provider.value}, enable_thinking={enable_thinking})")

    if provider == ModelProvider.DASHSCOPE:
        return _create_dashscope_chat_model(enable_thinking=enable_thinking)
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


def create_classifier_model():
    """
    创建分类器专用 Chat 模型（轻量、快速）

    环境变量 CLASSIFIER_MODEL 指定模型名，默认根据 provider 选择轻量版：
    - dashscope → qwen3-flash
    - ollama    → qwen3:0.6b

    如果轻量模型不可用，退化为使用主模型。

    Returns:
        LangChain ChatModel 实例
    """
    provider = get_provider()

    if provider == ModelProvider.DASHSCOPE:
        model_name = os.getenv("CLASSIFIER_MODEL", "qwen3-flash")
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            logger.warning("DASHSCOPE_API_KEY 未配置，分类器退化为使用主模型")
            return create_chat_model()

        logger.info(f"创建分类器模型: {model_name} (DashScope)")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=DASHSCOPE_BASE_URL,
            streaming=False,  # 分类器不需要流式
            http_async_client=get_shared_async_client(),
            request_timeout=30.0,
            # 思考模式由环境变量 CLASSIFIER_ENABLE_THINKING 控制，默认关闭：
            # qwen3-flash 开启思考会拖到 30s+ 导致 L2 分类超时降级
            extra_body={"enable_thinking": _env_bool("CLASSIFIER_ENABLE_THINKING", False)},
        )
    else:
        # Ollama
        model_name = os.getenv("CLASSIFIER_MODEL", "qwen3:0.6b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        logger.info(f"创建分类器模型: {model_name} (Ollama)")
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model_name,
            base_url=base_url,
            timeout=10.0,
            streaming=False,
        )


def create_plan_model():
    """
    创建 Plan 阶段专用 Chat 模型（轻量、支持结构化输出）

    环境变量 PLAN_MODEL 指定模型名，默认复用分类器模型配置。

    Returns:
        LangChain ChatModel 实例
    """
    provider = get_provider()

    if provider == ModelProvider.DASHSCOPE:
        model_name = os.getenv("PLAN_MODEL", "qwen3-flash")
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        if not api_key:
            logger.warning("DASHSCOPE_API_KEY 未配置，Plan 模型退化为使用主模型")
            return create_chat_model()

        logger.info(f"创建 Plan 模型: {model_name} (DashScope)")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=DASHSCOPE_BASE_URL,
            streaming=False,
            http_async_client=get_shared_async_client(),
            request_timeout=30.0,
            # 思考模式由环境变量 PLAN_ENABLE_THINKING 控制，默认关闭：
            # qwen3-flash 开启思考在规划任务上耗时 30s+（实测 46.7s 超时），
            # 会耗尽 plan_timeout 预算；关闭后实测 2.4s 返回完整 JSON 计划。
            extra_body={"enable_thinking": _env_bool("PLAN_ENABLE_THINKING", False)},
        )
    else:
        model_name = os.getenv("PLAN_MODEL", "qwen3:0.6b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        logger.info(f"创建 Plan 模型: {model_name} (Ollama)")
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model_name,
            base_url=base_url,
            timeout=15.0,
            streaming=False,
        )


# ============================================================
# DashScope（阿里云百炼）实现
# ============================================================

# DashScope OpenAI 兼容端点
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _create_dashscope_chat_model(enable_thinking: bool = False):
    """
    创建 DashScope Chat 模型（阿里云百炼）

    使用 ChatOpenAI + DashScope 的 OpenAI 兼容端点，
    避免 ChatTongyi 对部分新模型的 URL 构造问题。

    环境变量：
    - DASHSCOPE_API_KEY: API 密钥（必需）
    - DASHSCOPE_CHAT_MODEL: 模型名称（默认 qwen3-max）

    Args:
        enable_thinking: 是否开启思考模式（前端"深度思考"开关）

    Returns:
        ChatOpenAI 实例（指向 DashScope 兼容端点）
    """
    from langchain_openai import ChatOpenAI

    model_name = os.getenv("DASHSCOPE_CHAT_MODEL", "qwen3-max")
    api_key = os.getenv("DASHSCOPE_API_KEY", "")

    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY 未配置，请在 .env 中设置")

    logger.info(f"DashScope Chat 模型: {model_name} @ {DASHSCOPE_BASE_URL} (enable_thinking={enable_thinking})")

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=DASHSCOPE_BASE_URL,
        streaming=True,
        http_async_client=get_shared_async_client(),  # 复用连接池
        request_timeout=120.0,                         # 超时保护
        # 思考模式：由调用方（前端"深度思考"开关）决定
        extra_body={"enable_thinking": enable_thinking},
    )


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
