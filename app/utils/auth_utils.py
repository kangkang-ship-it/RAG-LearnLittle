"""
认证工具模块

提供 JWT 认证相关功能：
- JWT Token 编解码（Access Token + Refresh Token）
- 密码哈希（bcrypt）
- FastAPI 依赖注入：get_current_user_id 从请求中提取当前用户 ID
- 登录失败计数与账户锁定（Redis）
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.core.failed_response import BusinessError, ErrorCode
from app.db.database import get_db
from app.db.redis_client import get_redis
from app.models.user import User

# ========== 配置 ==========

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# 密码哈希上下文（bcrypt）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 登录锁定配置
MAX_LOGIN_ATTEMPTS = 5          # 最大失败次数
LOCKOUT_DURATION = 900          # 锁定时长（秒）= 15 分钟


# ========== 密码哈希 ==========

def hash_password(password: str) -> str:
    """
    对明文密码进行 bcrypt 哈希
    
    Args:
        password: 明文密码
        
    Returns:
        bcrypt 哈希后的密码字符串
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证明文密码是否与哈希值匹配
    
    Args:
        plain_password: 明文密码
        hashed_password: 存储的 bcrypt 哈希值
        
    Returns:
        匹配返回 True，否则 False
    """
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    验证密码强度
    
    要求：
    - 最小长度 8 位
    - 至少包含字母 + 数字
    
    Args:
        password: 待验证的密码
        
    Returns:
        (是否通过, 错误消息)
    """
    if len(password) < 8:
        return False, "密码长度至少 8 位"
    if not any(c.isalpha() for c in password):
        return False, "密码必须包含字母"
    if not any(c.isdigit() for c in password):
        return False, "密码必须包含数字"
    return True, ""


# ========== JWT Token ==========

def create_access_token(user_id: str, extra_claims: Optional[dict] = None) -> str:
    """
    创建 Access Token（短生命周期）
    
    Args:
        user_id: 用户 UUID
        extra_claims: 额外的 JWT payload 字段
        
    Returns:
        编码后的 JWT 字符串
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "exp": expire,
        "jti": str(uuid.uuid4()),      # 唯一标识，用于黑名单
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> tuple[str, str]:
    """
    创建 Refresh Token（长生命周期）
    
    同时在 Redis 白名单中记录该 Token，用于续期时校验。
    
    Args:
        user_id: 用户 UUID
        
    Returns:
        (token_string, jti): 编码后的 JWT 和唯一标识
    """
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    payload = {
        "sub": user_id,
        "exp": expire,
        "jti": jti,
        "type": "refresh",
    }
    
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict:
    """
    解码并验证 JWT Token
    
    Args:
        token: JWT 字符串
        
    Returns:
        解码后的 payload 字典
        
    Raises:
        BusinessError: Token 无效或已过期
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError as e:
        error_msg = str(e)
        if "expired" in error_msg.lower():
            raise BusinessError(
                code=ErrorCode.TOKEN_EXPIRED,
                detail=error_msg,
                http_status=401
            )
        raise BusinessError(
            code=ErrorCode.TOKEN_INVALID,
            detail=error_msg,
            http_status=401
        )


# ========== 登录锁定 ==========

async def check_login_attempts(username: str) -> None:
    """
    检查用户是否被锁定（登录失败次数过多）
    
    Args:
        username: 用户名
        
    Raises:
        BusinessError: 账户已锁定
    """
    redis = get_redis()
    attempts = await redis.get(f"login_attempts:{username}")
    if attempts and int(attempts) >= MAX_LOGIN_ATTEMPTS:
        raise BusinessError(
            code=ErrorCode.ACCOUNT_LOCKED,
            http_status=403
        )


async def record_login_failure(username: str) -> None:
    """
    记录登录失败次数
    
    Args:
        username: 用户名
    """
    redis = get_redis()
    key = f"login_attempts:{username}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, LOCKOUT_DURATION)
    
    logger.warning(f"登录失败: username={username}, attempts={count}")


async def clear_login_attempts(username: str) -> None:
    """
    登录成功后清除失败计数
    
    Args:
        username: 用户名
    """
    redis = get_redis()
    await redis.delete(f"login_attempts:{username}")


# ========== Refresh Token 管理 ==========

async def store_refresh_token(user_id: str, jti: str) -> None:
    """
    将 Refresh Token 存入 Redis 白名单
    
    Args:
        user_id: 用户 UUID
        jti: Token 唯一标识
    """
    redis = get_redis()
    key = f"refresh_token:{user_id}:{jti}"
    ttl = REFRESH_TOKEN_EXPIRE_DAYS * 86400  # 转为秒
    await redis.setex(key, ttl, "1")


async def verify_refresh_token(user_id: str, jti: str) -> bool:
    """
    验证 Refresh Token 是否在白名单中
    
    Args:
        user_id: 用户 UUID
        jti: Token 唯一标识
        
    Returns:
        有效返回 True
    """
    redis = get_redis()
    key = f"refresh_token:{user_id}:{jti}"
    return bool(await redis.get(key))


async def revoke_refresh_token(user_id: str, jti: str) -> None:
    """
    撤销 Refresh Token（从白名单中删除）
    
    Args:
        user_id: 用户 UUID
        jti: Token 唯一标识
    """
    redis = get_redis()
    await redis.delete(f"refresh_token:{user_id}:{jti}")


async def revoke_all_refresh_tokens(user_id: str) -> None:
    """
    撤销用户所有 Refresh Token（如修改密码后）
    
    Args:
        user_id: 用户 UUID
    """
    redis = get_redis()
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=f"refresh_token:{user_id}:*", count=100)
        if keys:
            await redis.delete(*keys)
        if cursor == 0:
            break


# ========== Access Token 黑名单 ==========

async def blacklist_access_token(jti: str, remaining_ttl: int) -> None:
    """
    将 Access Token 加入黑名单（登出时）
    
    Args:
        jti: Token 唯一标识
        remaining_ttl: Token 剩余有效期（秒）
    """
    redis = get_redis()
    key = f"token_blacklist:{jti}"
    await redis.setex(key, remaining_ttl, "1")


async def is_token_blacklisted(jti: str) -> bool:
    """
    检查 Access Token 是否在黑名单中
    
    Args:
        jti: Token 唯一标识
        
    Returns:
        在黑名单返回 True
    """
    redis = get_redis()
    return bool(await redis.get(f"token_blacklist:{jti}"))


# ========== FastAPI 依赖注入 ==========

async def get_current_user_id(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> str:
    """
    FastAPI 依赖注入：从 Authorization Header 中提取当前用户 ID
    
    流程：
    1. 解析 Bearer Token
    2. 解码 JWT
    3. 检查是否在黑名单中
    4. 返回 user_id
    
    Args:
        authorization: Authorization 请求头
        db: 数据库会话
        
    Returns:
        当前用户的 UUID
        
    Raises:
        BusinessError: 认证失败
    """
    if not authorization:
        raise BusinessError(
            code=ErrorCode.TOKEN_INVALID,
            message="缺少认证信息",
            http_status=401
        )
    
    # 解析 Bearer Token
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise BusinessError(
            code=ErrorCode.TOKEN_INVALID,
            message="Authorization 格式错误，应为 'Bearer <token>'",
            http_status=401
        )
    
    token = parts[1]
    
    # 解码 JWT
    payload = decode_token(token)
    
    # 验证类型
    if payload.get("type") != "access":
        raise BusinessError(
            code=ErrorCode.TOKEN_INVALID,
            message="Token 类型错误",
            http_status=401
        )
    
    # 检查黑名单
    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise BusinessError(
            code=ErrorCode.TOKEN_INVALID,
            message="Token 已被撤销",
            http_status=401
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise BusinessError(
            code=ErrorCode.TOKEN_INVALID,
            http_status=401
        )
    
    return user_id
