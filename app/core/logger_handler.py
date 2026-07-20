"""
日志配置模块

提供 JSON 结构化日志功能：
- 开发环境输出到控制台（DEBUG 级别）
- 生产环境输出到按日期滚动的文件（INFO 级别）
- 敏感信息（password、token、Authorization）自动脱敏
- JSON 格式便于日志采集系统解析
"""

import logging
import os
import re
import json
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# 敏感字段正则模式：匹配 password、token、Authorization 等关键字的值
_SENSITIVE_PATTERNS = re.compile(
    r'((?:password|token|authorization|secret|api_key)["\s:=]+)["\']?[^"\',\s}]+["\']?',
    re.IGNORECASE
)

# 日志格式：JSON 结构化
_LOG_FORMAT = json.dumps({
    "timestamp": "%(asctime)s",
    "level": "%(levelname)s",
    "logger": "%(name)s",
    "message": "%(message)s",
    "module": "%(module)s",
    "function": "%(funcName)s",
    "line": "%(lineno)d"
}, ensure_ascii=False)


class SensitiveFilter:
    """
    日志过滤器：自动将敏感信息替换为 ***
    
    用于防止密码、Token、API Key 等敏感数据泄露到日志文件中。
    """

    @staticmethod
    def filter(message: str) -> str:
        """
        将消息中的敏感字段替换为 '***'
        
        Args:
            message: 原始日志消息
            
        Returns:
            脱敏后的消息字符串
        """
        return _SENSITIVE_PATTERNS.sub(r'\1"***"', str(message))


class JsonFormatter(logging.Formatter):
    """
    JSON 格式化器：将日志记录格式化为 JSON 字符串
    
    输出格式包含 timestamp、level、logger、message 等字段，
    方便日志采集系统（如 ELK Stack）解析。
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录为 JSON 字符串
        
        Args:
            record: 日志记录对象
            
        Returns:
            JSON 格式的日志字符串
        """
        # 先对 message 进行敏感信息过滤
        record.msg = SensitiveFilter.filter(record.getMessage())
        record.message = record.msg
        
        # 构建 JSON 日志条目
        log_entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # 如果有额外字段，合并到 extra 中
        if hasattr(record, 'extra_data'):
            log_entry["extra"] = record.extra_data
        
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logger(name: str = "raglearn") -> logging.Logger:
    """
    配置并返回日志记录器
    
    根据环境变量 LOG_LEVEL 决定日志级别：
    - 开发环境（默认）：DEBUG 级别，输出到控制台
    - 生产环境（LOG_LEVEL=INFO）：INFO 级别，输出到控制台 + 按日期滚动文件
    
    Args:
        name: 日志记录器名称，默认为 "raglearn"
        
    Returns:
        配置好的 Logger 实例
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    # 从环境变量获取日志级别，默认 DEBUG
    log_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, log_level, logging.DEBUG)
    logger.setLevel(level)
    
    # 使用 JSON 格式化器
    formatter = JsonFormatter(datefmt="%Y-%m-%d %H:%M:%S")
    
    # 控制台 Handler（始终启用）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件 Handler（生产环境启用）
    if log_level in ("INFO", "WARNING", "ERROR"):
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # 按日期滚动，保留 30 天日志
        file_handler = TimedRotatingFileHandler(
            filename=log_dir / "app.log",
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8"
        )
        file_handler.suffix = "%Y%m%d"
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# 全局日志实例
logger = setup_logger()
