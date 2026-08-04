"""
文件处理工具模块

提供文件上传校验、MD5 计算、文件类型检测等功能。
"""

import hashlib
import os
from dataclasses import dataclass
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

# ========== 聊天附件（图片/视频）支持类型 ==========

# 支持的扩展名集合
CHAT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CHAT_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi"}

# 扩展名 → (file_type, mime_type, magic bytes 签名组)
# 签名组格式：[[(offset, bytes), ...], ...]，命中任意一组即通过（如 GIF87a/GIF89a 两种）
# 所有签名均为"前缀匹配"：content[offset:offset+len(magic)] == magic
_CHAT_EXT_SPECS = {
    ".png":  ("image", "image/png",           [[(0, b"\x89PNG\r\n\x1a\n")]]),
    ".jpg":  ("image", "image/jpeg",          [[(0, b"\xff\xd8\xff")]]),
    ".jpeg": ("image", "image/jpeg",          [[(0, b"\xff\xd8\xff")]]),
    ".webp": ("image", "image/webp",          [[(0, b"RIFF"), (8, b"WEBP")]]),
    ".gif":  ("image", "image/gif",           [[(0, b"GIF87a")], [(0, b"GIF89a")]]),
    ".mp4":  ("video", "video/mp4",           [[(4, b"ftyp")]]),
    ".webm": ("video", "video/webm",          [[(0, b"\x1a\x45\xdf\xa3")]]),
    ".mov":  ("video", "video/quicktime",     [[(4, b"ftyp")]]),
    ".avi":  ("video", "video/x-msvideo",     [[(0, b"RIFF"), (8, b"AVI ")]]),
}


@dataclass
class AttachmentInfo:
    """聊天附件校验结果"""
    file_type: str   # image / video
    mime_type: str   # 如 image/png
    ext: str         # 标准化扩展名（含点，如 .png）


def _match_magic(content: bytes, signature_groups: list) -> bool:
    """
    校验文件内容 magic bytes 签名

    每组签名内的所有 (offset, bytes) 必须全部命中；多组之间命中任意一组即可。

    Args:
        content: 文件内容字节
        signature_groups: 签名组列表

    Returns:
        是否匹配
    """
    if not content:
        return False
    for group in signature_groups:
        if all(
            content[offset:offset + len(magic)] == magic
            for offset, magic in group
        ):
            return True
    return False


def validate_chat_attachment(
    filename: str,
    file_size: int,
    content: bytes,
    max_size_mb: int = 10,
) -> AttachmentInfo:
    """
    校验聊天附件（图片/视频）是否合规（纵深防御：扩展名白名单 + magic bytes 双重校验）

    检查项：
    1. 文件大小不超过限制
    2. 扩展名在图片/视频白名单中（png/jpg/jpeg/webp/gif + mp4/webm/mov/avi）
    3. 文件内容 magic bytes 与扩展名声称的类型一致（杜绝伪装扩展名）

    注意：独立于 validate_upload_file（知识库 PDF/MD/TXT）与 validate_avatar_file，
    不复用、不修改现有函数，避免影响知识库上传路径。

    Args:
        filename: 原始文件名
        file_size: 文件大小（字节）
        content: 文件内容字节（用于 magic bytes 校验）
        max_size_mb: 最大文件大小（MB）

    Returns:
        AttachmentInfo 校验结果

    Raises:
        BusinessError: 文件校验失败
    """
    max_size_bytes = max_size_mb * 1024 * 1024
    if file_size > max_size_bytes:
        raise BusinessError(
            code=ErrorCode.FILE_TOO_LARGE,
            detail=f"文件大小 {file_size / 1024 / 1024:.1f}MB 超过限制 {max_size_mb}MB"
        )

    ext = Path(filename).suffix.lower()

    if ext in FORBIDDEN_EXTENSIONS:
        raise BusinessError(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            detail=f"禁止上传 {ext} 类型的文件"
        )

    spec = _CHAT_EXT_SPECS.get(ext)
    if spec is None:
        raise BusinessError(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            detail=f"不支持的文件类型: {ext}，仅支持图片（PNG/JPG/WebP/GIF）和视频（MP4/WebM/MOV/AVI）"
        )

    file_type, mime_type, signature_groups = spec

    # magic bytes 校验（内容签名与扩展名一致才接受）
    if not _match_magic(content, signature_groups):
        raise BusinessError(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            detail=f"文件内容与扩展名 {ext} 不符，已拒绝上传"
        )

    return AttachmentInfo(file_type=file_type, mime_type=mime_type, ext=ext)


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
