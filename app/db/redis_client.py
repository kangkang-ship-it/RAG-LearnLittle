"""
Redis 缓存配置模块

提供异步 Redis 连接和通用缓存能力：
- 异步连接池（redis.asyncio）
- RedisCache 泛型类：通用的 get_or_set 缓存模式
- cache_with_redis 装饰器：一行注解为异步函数添加 Redis 缓存
- 支持按模式批量删除缓存（delete_pattern）
"""

import json
import os
import hashlib
import functools
from typing import Any, Callable, Optional, TypeVar

import redis.asyncio as aioredis

from app.core.logger_handler import logger

# ========== Redis 连接配置 ==========

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "3"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None) or None  # 空字符串转为 None

# Redis 连接池
redis_pool: Optional[aioredis.Redis] = None


async def init_redis() -> aioredis.Redis:
    """
    初始化 Redis 连接池
    
    创建异步 Redis 连接并验证连接是否正常。
    连接池挂载到 FastAPI app.state.redis 上供全局使用。
    
    Returns:
        aioredis.Redis: Redis 异步连接实例
    """
    global redis_pool
    
    redis_pool = aioredis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD,
        decode_responses=True,    # 自动将 bytes 解码为 str
        max_connections=50,       # 连接池最大连接数
    )
    
    # 验证连接
    try:
        await redis_pool.ping()
        logger.info(f"Redis 连接成功: {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
    except Exception as e:
        logger.error(f"Redis 连接失败: {e}")
        raise
    
    return redis_pool


async def close_redis() -> None:
    """
    关闭 Redis 连接池
    
    在应用关闭时调用，释放所有 Redis 连接资源。
    """
    global redis_pool
    if redis_pool:
        await redis_pool.close()
        redis_pool = None
        logger.info("Redis 连接池已关闭")


def get_redis() -> aioredis.Redis:
    """
    获取 Redis 连接实例
    
    Returns:
        aioredis.Redis: Redis 异步连接
        
    Raises:
        RuntimeError: Redis 未初始化时抛出
    """
    if redis_pool is None:
        raise RuntimeError("Redis 未初始化，请先调用 init_redis()")
    return redis_pool


# ========== 通用缓存工具 ==========

F = TypeVar("F", bound=Callable)


class RedisCache:
    """
    Redis 通用缓存类
    
    提供 get_or_set 模式：先查缓存，未命中则执行回调函数并写入缓存。
    支持对象自动 JSON 序列化/反序列化。
    """
    
    def __init__(self, redis_client: aioredis.Redis, default_ttl: int = 3600):
        """
        初始化缓存实例
        
        Args:
            redis_client: Redis 异步连接
            default_ttl: 默认缓存过期时间（秒），默认 1 小时
        """
        self.redis = redis_client
        self.default_ttl = default_ttl
    
    async def get(self, key: str) -> Optional[Any]:
        """
        从缓存获取数据
        
        Args:
            key: 缓存键
            
        Returns:
            缓存的数据（已反序列化），不存在返回 None
        """
        data = await self.redis.get(key)
        if data is None:
            return None
        return json.loads(data)
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        写入缓存
        
        Args:
            key: 缓存键
            value: 要缓存的数据（会自动 JSON 序列化）
            ttl: 过期时间（秒），不传则使用默认值
        """
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        await self.redis.set(key, serialized, ex=ttl or self.default_ttl)
    
    async def get_or_set(
        self, key: str, factory: Callable, ttl: Optional[int] = None
    ) -> Any:
        """
        缓存穿透模式：先查缓存，未命中则执行 factory 函数并缓存结果
        
        Args:
            key: 缓存键
            factory: 缓存未命中时的数据获取函数（可以是异步函数）
            ttl: 过期时间（秒）
            
        Returns:
            缓存或新生成的数据
        """
        # 先查缓存
        cached = await self.get(key)
        if cached is not None:
            return cached
        
        # 缓存未命中，执行 factory
        import asyncio
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()
        
        # 写入缓存
        await self.set(key, value, ttl)
        return value
    
    async def delete(self, key: str) -> None:
        """
        删除缓存
        
        Args:
            key: 缓存键
        """
        await self.redis.delete(key)
    
    async def delete_pattern(self, pattern: str) -> None:
        """
        按模式批量删除缓存
        
        使用 SCAN 命令（非 KEYS）避免阻塞 Redis。
        
        Args:
            pattern: 匹配模式，如 "chat:sessions:123*"
        """
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break


async def delete_pattern(redis_client: aioredis.Redis, pattern: str) -> None:
    """
    按模式批量删除缓存（独立函数版本）
    
    Args:
        redis_client: Redis 异步连接
        pattern: 匹配模式
    """
    cursor = 0
    while True:
        cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
        if keys:
            await redis_client.delete(*keys)
        if cursor == 0:
            break


def cache_with_redis(ttl: int = 3600, key_prefix: str = "cache"):
    """
    Redis 缓存装饰器
    
    为异步函数自动添加 Redis 缓存。缓存键由函数名和参数哈希生成。
    
    使用示例：
        @cache_with_redis(ttl=300, key_prefix="notes")
        async def get_note_stats(user_id: str) -> dict:
            ...
    
    Args:
        ttl: 缓存过期时间（秒）
        key_prefix: 缓存键前缀
        
    Returns:
        装饰器函数
    """
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存键：prefix:function_name:args_hash
            args_str = f"{args}_{kwargs}"
            args_hash = hashlib.md5(args_str.encode()).hexdigest()[:16]
            cache_key = f"{key_prefix}:{func.__name__}:{args_hash}"
            
            # 尝试从缓存获取
            redis = get_redis()
            cached = await redis.get(cache_key)
            if cached is not None:
                return json.loads(cached)
            
            # 执行原函数
            result = await func(*args, **kwargs)
            
            # 写入缓存
            serialized = json.dumps(result, ensure_ascii=False, default=str)
            await redis.set(cache_key, serialized, ex=ttl)
            
            return result
        
        return wrapper
    
    return decorator
