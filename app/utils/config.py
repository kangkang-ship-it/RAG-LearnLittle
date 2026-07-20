"""
YAML 配置加载工具

从 config/ 目录加载 YAML 配置文件，提供统一的配置访问接口。
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml

from app.core.logger_handler import logger

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 配置目录
CONFIG_DIR = BASE_DIR / "config"


def load_yaml(filename: str) -> dict:
    """
    加载指定的 YAML 配置文件
    
    Args:
        filename: 配置文件名（如 "chroma.yaml"）
        
    Returns:
        解析后的字典
        
    Raises:
        FileNotFoundError: 配置文件不存在
    """
    filepath = CONFIG_DIR / filename
    
    if not filepath.exists():
        logger.error(f"配置文件不存在: {filepath}")
        raise FileNotFoundError(f"配置文件不存在: {filepath}")
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    logger.debug(f"加载配置文件: {filename}")
    return data or {}


def get_chroma_config() -> dict:
    """
    获取 ChromaDB 配置
    
    Returns:
        chroma.yaml 中的配置字典
    """
    return load_yaml("chroma.yaml").get("chroma", {})


def get_prompt_config() -> dict:
    """
    获取 Prompt 路径映射配置
    
    Returns:
        prompt.yaml 中的配置字典
    """
    return load_yaml("prompt.yaml").get("prompts", {})


def get_agent_config() -> dict:
    """
    获取 Agent 配置
    
    Returns:
        agent.yaml 中的配置字典
    """
    return load_yaml("agent.yaml").get("agent", {})
