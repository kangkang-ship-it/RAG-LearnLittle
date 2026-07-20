"""
认证相关 Pydantic Schema

定义用户注册、登录、Token 刷新等接口的请求和响应模型。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class UserRegister(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=8, max_length=128, description="密码")
    email: Optional[str] = Field(None, description="邮箱（可选）")
    
    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        """用户名只能包含字母、数字和下划线"""
        if not v.replace("_", "").isalnum():
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """密码必须包含字母和数字"""
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含字母")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含数字")
        return v


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")
    device_id: Optional[str] = Field(None, description="设备唯一标识（前端生成并持久化）")
    device_name: Optional[str] = Field(None, description="设备可读名称，如 Chrome on Windows")


class TokenResponse(BaseModel):
    """登录成功返回的 Token 信息"""
    access_token: str = Field(..., description="Access Token（JWT）")
    refresh_token: str = Field(..., description="Refresh Token（JWT）")
    token_type: str = Field(default="bearer", description="Token 类型")
    expires_in: int = Field(..., description="Access Token 过期时间（秒）")
    device_id: Optional[str] = Field(None, description="回传设备标识，前端应持久化存储")


class RefreshTokenRequest(BaseModel):
    """Token 刷新请求"""
    refresh_token: str = Field(..., description="Refresh Token")
    device_id: Optional[str] = Field(None, description="设备唯一标识")


class SessionInfo(BaseModel):
    """会话信息（用于会话列表）"""
    device_id: str = Field(..., description="设备唯一标识")
    device_name: Optional[str] = Field(None, description="设备可读名称，如 Chrome on Windows")
    ip: Optional[str] = Field(None, description="最近登录 IP")
    created_at: Optional[str] = Field(None, description="会话创建时间（ISO 8601）")
    last_used: Optional[str] = Field(None, description="最后活跃时间（ISO 8601）")
    is_current: bool = Field(default=False, description="是否为当前请求设备")


class UserUpdate(BaseModel):
    """用户信息更新请求"""
    bio: Optional[str] = Field(None, max_length=500, description="个人简介")
    email: Optional[str] = Field(None, description="邮箱")


class PasswordChange(BaseModel):
    """密码修改请求"""
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=8, max_length=128, description="新密码")
    
    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """新密码必须包含字母和数字"""
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含字母")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含数字")
        return v


class UserInfo(BaseModel):
    """用户信息响应"""
    uuid: str
    username: str
    email: Optional[str] = None
    avatar: Optional[str] = None
    bio: Optional[str] = None
    status: str
    created_at: datetime
    
    model_config = {"from_attributes": True}
