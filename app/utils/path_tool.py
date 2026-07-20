"""
路径工具模块

提供项目内绝对路径转换功能，避免硬编码相对路径。
"""

from pathlib import Path

# 项目根目录（app/utils/path_tool.py 向上三级）
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def get_project_root() -> Path:
    """
    获取项目根目录的绝对路径
    
    Returns:
        项目根目录 Path 对象
    """
    return BASE_DIR


def get_data_dir() -> Path:
    """
    获取 data/ 目录的绝对路径（ChromaDB、MD5 等数据）
    
    Returns:
        data 目录 Path 对象（不存在则自动创建）
    """
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def get_logs_dir() -> Path:
    """
    获取 logs/ 目录的绝对路径
    
    Returns:
        logs 目录 Path 对象（不存在则自动创建）
    """
    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(exist_ok=True)
    return logs_dir


def get_media_dir() -> Path:
    """
    获取 media/ 目录的绝对路径（用户头像、上传文件等）
    
    Returns:
        media 目录 Path 对象（不存在则自动创建）
    """
    media_dir = BASE_DIR / "media"
    media_dir.mkdir(exist_ok=True)
    return media_dir


def get_config_dir() -> Path:
    """
    获取 config/ 目录的绝对路径
    
    Returns:
        config 目录 Path 对象
    """
    return BASE_DIR / "config"


def get_prompts_dir() -> Path:
    """
    获取 prompts/ 目录的绝对路径
    
    Returns:
        prompts 目录 Path 对象
    """
    return BASE_DIR / "prompts"


def abs_path(relative_path: str) -> Path:
    """
    将相对路径转换为项目内的绝对路径
    
    Args:
        relative_path: 相对于项目根目录的路径
        
    Returns:
        绝对路径 Path 对象
        
    示例：
        abs_path("data/chroma") → /path/to/project/data/chroma
    """
    return BASE_DIR / relative_path
