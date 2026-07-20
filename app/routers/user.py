"""
用户认证路由

端点：
- POST /auth/register - 用户注册
- POST /auth/login - 用户登录
- POST /auth/logout - 用户登出
- POST /auth/refresh - Token 刷新
- POST /auth/sse-token - 获取 SSE 短期 Token
- GET /user/me - 获取当前用户信息
- PUT /user/me - 更新用户信息
- POST /user/me/password - 修改密码
- POST /file/avatar - 上传头像
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger_handler import logger
from app.core.success_response import success_response
from app.core.failed_response import BusinessError, ErrorCode
from app.core.rate_limit import rate_limit
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import (
    UserRegister, UserLogin, TokenResponse,
    RefreshTokenRequest, UserUpdate, PasswordChange, UserInfo,
)
from app.utils.auth_utils import (
    hash_password, verify_password, validate_password_strength,
    create_access_token, create_refresh_token, decode_token,
    get_current_user_id, check_login_attempts, record_login_failure,
    clear_login_attempts, store_refresh_token, verify_refresh_token,
    revoke_refresh_token, revoke_all_refresh_tokens, blacklist_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from app.db.redis_client import get_redis
from app.utils.file_handler import validate_avatar_file, get_safe_filename, ensure_dir

router = APIRouter()


@router.post("/auth/register", summary="用户注册")
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    """
    注册新用户
    
    校验用户名唯一性，密码强度，创建用户记录。
    """
    # 检查用户名是否已存在
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise BusinessError(code=ErrorCode.USERNAME_EXISTS, http_status=409)
    
    # 校验密码强度
    is_valid, error_msg = validate_password_strength(data.password)
    if not is_valid:
        raise BusinessError(code=ErrorCode.INVALID_PARAMETER, message=error_msg)
    
    # 创建用户
    user = User(
        uuid=str(uuid.uuid4()),
        username=data.username,
        email=data.email,
        password=hash_password(data.password),
    )
    db.add(user)
    await db.flush()
    
    logger.info(f"用户注册成功: username={data.username}, id={user.uuid}")
    
    return success_response(data={"user_id": user.uuid, "username": user.username})


@router.post("/auth/login", summary="用户登录", dependencies=[Depends(rate_limit(endpoint_limit=5))])
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """
    用户登录
    
    校验用户名密码，返回 Access Token + Refresh Token。
    连续 5 次失败锁定 15 分钟。
    """
    # 检查是否被锁定
    await check_login_attempts(data.username)
    
    # 查找用户
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(data.password, user.password):
        await record_login_failure(data.username)
        raise BusinessError(code=ErrorCode.PASSWORD_ERROR, http_status=401)
    
    # 登录成功，清除失败计数
    await clear_login_attempts(data.username)
    
    # 生成令牌对
    access_token = create_access_token(user.uuid)
    refresh_token, jti = create_refresh_token(user.uuid)
    
    # 存储 Refresh Token 白名单
    await store_refresh_token(user.uuid, jti)
    
    logger.info(f"用户登录成功: username={data.username}")
    
    return success_response(data=TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    ).model_dump())


@router.post("/auth/logout", summary="用户登出")
async def logout(
    user_id: str = Depends(get_current_user_id),
    authorization: str = Depends(lambda h: h.get("Authorization", "")),
):
    """
    用户登出
    
    将 Access Token 加入黑名单，删除 Refresh Token 白名单。
    """
    # 解析当前 Token 的 jti
    token = authorization.split()[-1] if authorization else ""
    payload = decode_token(token)
    jti = payload.get("jti")
    
    if jti:
        # 计算剩余有效期
        from datetime import datetime, timezone
        exp = payload.get("exp", 0)
        remaining = max(0, int(exp - datetime.now(timezone.utc).timestamp()))
        await blacklist_access_token(jti, remaining)
    
    # 删除所有 Refresh Token
    await revoke_all_refresh_tokens(user_id)
    
    logger.info(f"用户登出: user_id={user_id}")
    return success_response(message="登出成功")


@router.post("/auth/refresh", summary="刷新 Token")
async def refresh_token(data: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    """
    刷新 Token（Rotation 防重放）
    
    校验 Refresh Token → 签发新令牌对 → 旧 Refresh Token 立即失效。
    """
    # 解码 Refresh Token
    payload = decode_token(data.refresh_token)
    
    if payload.get("type") != "refresh":
        raise BusinessError(code=ErrorCode.REFRESH_TOKEN_INVALID, http_status=401)
    
    user_id = payload.get("sub")
    jti = payload.get("jti")
    
    # 验证白名单
    if not await verify_refresh_token(user_id, jti):
        raise BusinessError(code=ErrorCode.REFRESH_TOKEN_INVALID, http_status=401)
    
    # 旧 Token 立即失效（Rotation）
    await revoke_refresh_token(user_id, jti)
    
    # 签发新令牌对
    new_access = create_access_token(user_id)
    new_refresh, new_jti = create_refresh_token(user_id)
    await store_refresh_token(user_id, new_jti)
    
    return success_response(data=TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    ).model_dump())


@router.post("/auth/sse-token", summary="获取 SSE 短期 Token")
async def get_sse_token(user_id: str = Depends(get_current_user_id)):
    """
    用有效 Access Token 换取 60 秒一次性 SSE Token
    
    SSE 连接无法携带自定义 Header，使用短期 Query Token 替代。
    """
    import uuid as _uuid
    redis = get_redis()
    
    sse_jti = str(_uuid.uuid4())
    sse_token = create_access_token(user_id, extra_claims={"type": "sse", "jti": sse_jti})
    
    # 存入 Redis，60 秒过期，一次性使用
    await redis.setex(f"sse_token:{sse_jti}", 60, user_id)
    
    return success_response(data={"token": sse_token, "expires_in": 60})


@router.get("/user/me", summary="获取当前用户信息")
async def get_user_info(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """获取当前登录用户的详细信息"""
    result = await db.execute(select(User).where(User.uuid == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise BusinessError(code=ErrorCode.USER_NOT_FOUND, http_status=404)
    
    return success_response(data=UserInfo.model_validate(user).model_dump())


@router.put("/user/me", summary="更新用户信息")
async def update_user_info(
    data: UserUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """更新当前用户的个人资料"""
    result = await db.execute(select(User).where(User.uuid == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise BusinessError(code=ErrorCode.USER_NOT_FOUND, http_status=404)
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    
    await db.flush()
    return success_response(message="更新成功")


@router.post("/user/me/password", summary="修改密码")
async def change_password(
    data: PasswordChange,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    修改密码
    
    需提供旧密码验证，修改后所有 Refresh Token 立即失效。
    """
    result = await db.execute(select(User).where(User.uuid == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise BusinessError(code=ErrorCode.USER_NOT_FOUND, http_status=404)
    
    if not verify_password(data.old_password, user.password):
        raise BusinessError(code=ErrorCode.PASSWORD_ERROR, http_status=403)
    
    # 校验新密码强度
    is_valid, error_msg = validate_password_strength(data.new_password)
    if not is_valid:
        raise BusinessError(code=ErrorCode.INVALID_PARAMETER, message=error_msg)
    
    user.password = hash_password(data.new_password)
    await db.flush()
    
    # 所有 Refresh Token 失效
    await revoke_all_refresh_tokens(user_id)
    
    logger.info(f"密码修改成功: user_id={user_id}")
    return success_response(message="密码修改成功")


# ========== 头像上传 ==========

# 头像存储目录（相对于项目根目录）
AVATAR_DIR = "data/avatars"


@router.post("/file/avatar", summary="上传头像")
async def upload_avatar(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    上传用户头像

    支持 PNG / JPG / WebP 格式，单文件上限 5MB。
    上传成功后自动更新用户 avatar 字段，返回可访问的头像 URL。
    """
    # 读取文件内容
    content = await file.read()
    file_size = len(content)

    # 校验头像文件（格式 + 大小）
    ext = validate_avatar_file(file.filename, file_size)

    # 保存文件（以 user_id 分目录，文件名用时间戳避免冲突）
    avatar_dir = Path(AVATAR_DIR) / user_id
    ensure_dir(str(avatar_dir))

    timestamp = int(datetime.now().timestamp() * 1000)
    stored_name = f"avatar_{timestamp}{ext}"
    file_path = avatar_dir / stored_name

    with open(file_path, "wb") as f:
        f.write(content)

    # 删除旧头像文件（避免磁盘垃圾）
    result = await db.execute(select(User).where(User.uuid == user_id))
    user = result.scalar_one_or_none()
    if user and user.avatar:
        old_path = Path(user.avatar.lstrip("/"))
        if old_path.exists():
            try:
                old_path.unlink()
            except Exception as e:
                logger.warning(f"删除旧头像失败: {e}")

    # 更新用户头像 URL（静态文件服务路径）
    avatar_url = f"/static/avatars/{user_id}/{stored_name}"
    if user:
        user.avatar = avatar_url
        await db.flush()

    logger.info(f"头像上传成功: user_id={user_id}, url={avatar_url}")

    return success_response(data={
        "avatar_url": avatar_url,
        "filename": stored_name,
    })
