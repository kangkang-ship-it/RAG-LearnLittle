"""
文件处理工具模块

提供文件上传校验、MD5 计算、文件类型检测等功能。
"""

import hashlib
import os
from pathlib import Path
from typing import Optional

from app.core.logger_handler import logger
from app.core.failed_response import BusinessError, ErrorCode

# 支持的文件 MIME 类型
ALLOWED_MIME_TYPES = {
    "application/pdf": ".pdf",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/x-markdown": ".md",
}

# 支持的头像图片类型
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

# 禁止的文件扩展名（可执行文件、压缩包等）
FORBIDDEN_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr",  # Windows 可执行文件
    ".sh", ".bash", ".csh",                           # Unix 脚本
    ".zip", ".rar", ".7z", ".tar", ".gz",            # 压缩包
    ".dll", ".so", ".dylib",                          # 动态链接库
    ".bin",                                           # 二进制文件
}


def calculate_md5(file_path: str) -> str:
    """
    计算文件的 MD5 哈希值
    
    使用分块读取避免大文件内存溢出。
    
    Args:
        file_path: 文件路径
        
    Returns:
        32 位 MD5 哈希字符串（小写）
    """
    md5 = hashlib.md5()
    
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            md5.update(chunk)
    
    return md5.hexdigest()


def calculate_md5_bytes(data: bytes) -> str:
    """
    计算字节数据的 MD5 哈希值
    
    Args:
        data: 字节数据
        
    Returns:
        32 位 MD5 哈希字符串（小写）
    """
    return hashlib.md5(data).hexdigest()


def validate_upload_file(
    filename: str,
    file_size: int,
    max_size_mb: int = 50
) -> str:
    """
    校验上传文件是否合规
    
    检查项：
    1. 文件大小不超过限制
    2. 文件扩展名不在禁止列表中
    3. 文件扩展名在允许的类型中
    
    Args:
        filename: 原始文件名
        file_size: 文件大小（字节）
        max_size_mb: 最大文件大小（MB）
        
    Returns:
        标准化的文件扩展名（如 ".pdf"）
        
    Raises:
        BusinessError: 文件校验失败
    """
    # 检查文件大小
    max_size_bytes = max_size_mb * 1024 * 1024
    if file_size > max_size_bytes:
        raise BusinessError(
            code=ErrorCode.FILE_TOO_LARGE,
            detail=f"文件大小 {file_size / 1024 / 1024:.1f}MB 超过限制 {max_size_mb}MB"
        )
    
    # 检查文件扩展名
    ext = Path(filename).suffix.lower()
    
    if ext in FORBIDDEN_EXTENSIONS:
        raise BusinessError(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            detail=f"禁止上传 {ext} 类型的文件"
        )
    
    if ext not in {".pdf", ".md", ".txt"}:
        raise BusinessError(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            detail=f"不支持的文件类型: {ext}，仅支持 PDF / Markdown / TXT"
        )
    
    return ext


def get_safe_filename(filename: str) -> str:
    """
    生成安全的文件名（去除路径分隔符等特殊字符）
    
    Args:
        filename: 原始文件名
        
    Returns:
        安全的文件名
    """
    # 去除路径分隔符
    safe_name = filename.replace("/", "_").replace("\\", "_")
    # 去除空字符
    safe_name = safe_name.replace("\x00", "")
    return safe_name


def ensure_dir(dir_path: str) -> None:
    """
    确保目录存在，不存在则自动创建
    
    Args:
        dir_path: 目录路径
    """
    Path(dir_path).mkdir(parents=True, exist_ok=True)


def validate_avatar_file(filename: str, file_size: int, max_size_mb: int = 5) -> str:
    """
    校验头像文件是否合规

    检查项：
    1. 文件大小不超过限制（默认 5MB）
    2. 文件扩展名在允许的图片类型中（png/jpg/webp）

    Args:
        filename: 原始文件名
        file_size: 文件大小（字节）
        max_size_mb: 最大文件大小（MB），默认 5MB

    Returns:
        标准化的文件扩展名（如 ".png"）

    Raises:
        BusinessError: 文件校验失败
    """
    max_size_bytes = max_size_mb * 1024 * 1024
    if file_size > max_size_bytes:
        raise BusinessError(
            code=ErrorCode.FILE_TOO_LARGE,
            detail=f"头像文件大小 {file_size / 1024 / 1024:.1f}MB 超过限制 {max_size_mb}MB"
        )

    ext = Path(filename).suffix.lower()
    allowed_exts = {v for v in ALLOWED_IMAGE_TYPES.values()}

    if ext not in allowed_exts:
        raise BusinessError(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            detail=f"不支持的头像格式: {ext}，仅支持 PNG / JPG / WebP"
        )

    return ext


def get_file_size_str(file_size: int) -> str:
    """
    将文件大小（字节）转换为人类可读的字符串
    
    Args:
        file_size: 文件大小（字节）
        
    Returns:
        可读的文件大小字符串（如 "1.5 MB"）
    """
    if file_size < 1024:
        return f"{file_size} B"
    elif file_size < 1024 * 1024:
        return f"{file_size / 1024:.1f} KB"
    else:
        return f"{file_size / 1024 / 1024:.1f} MB"
