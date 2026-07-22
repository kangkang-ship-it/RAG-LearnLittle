"""
日志配置模块

提供两种日志格式：
- text（开发环境）：可读的纯文本格式，输出到控制台
- json（生产环境）：JSON 结构化日志，输出到控制台 + 按日期滚动的文件

敏感信息（password、token、Authorization）自动脱敏。
通过环境变量 LOG_FORMAT 和 LOG_LEVEL 控制。
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


class TextFormatter(logging.Formatter):
    """
    纯文本格式化器（开发环境使用）

    输出格式：时间 级别 [模块:行号] 消息
    示例：2026-07-21 17:10:50 INFO [user.py:131] 用户登录成功: username=admin, device_id=N/A
    """

    def __init__(self, datefmt: str = "%Y-%m-%d %H:%M:%S"):
        super().__init__(datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        # 先对 message 进行敏感信息过滤
        message = SensitiveFilter.filter(record.getMessage())

        # 格式化时间
        timestamp = self.formatTime(record, self.datefmt)

        # 拼接纯文本日志行
        location = f"{record.module}:{record.lineno}"
        return f"{timestamp} {record.levelname:<5} [{location:<20}] {message}"

    def formatTime(self, record, datefmt=None):
        """覆盖父类方法以支持 datefmt"""
        from time import strftime
        from datetime import datetime
        ct = datetime.fromtimestamp(record.created)
        if datefmt:
            return ct.strftime(datefmt)
        return ct.strftime("%Y-%m-%d %H:%M:%S")


class JsonFormatter(logging.Formatter):
    """
    JSON 格式化器（生产环境使用）

    输出格式包含 timestamp、level、logger、message 等字段，
    方便日志采集系统（如 ELK Stack）解析。
    
    """

    def __init__(self, datefmt: str = "%Y-%m-%d %H:%M:%S"):
        super().__init__(datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        """
        格式化日志记录为 JSON 字符串

        Args:
            record: 日志记录对象

        Returns:
            JSON 格式的日志字符串
        """
        # 先对 message 进行敏感信息过滤
        message = SensitiveFilter.filter(record.getMessage())

        # 构建 JSON 日志条目
        log_entry = {
            "timestamp": self._format_time(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }

        # 如果有额外字段，合并到 extra 中
        if hasattr(record, 'extra_data'):
            log_entry["extra"] = record.extra_data

        return json.dumps(log_entry, ensure_ascii=False)

    def _format_time(self, timestamp: float) -> str:
        """将时间戳格式化为字符串"""
        from datetime import datetime
        ct = datetime.fromtimestamp(timestamp)
        if self.datefmt:
            return ct.strftime(self.datefmt)
        return ct.strftime("%Y-%m-%d %H:%M:%S")


def setup_logger(name: str = "raglearn") -> logging.Logger:
    """
    配置并返回日志记录器

    根据环境变量控制输出格式和目标：
    - LOG_FORMAT: "text"（默认，开发环境）或 "json"（生产环境）
    - LOG_LEVEL: DEBUG（默认）/ INFO / WARNING / ERROR

    text 模式：纯文本格式，仅输出到控制台
    json 模式：JSON 格式，输出到控制台 + 按日期滚动的文件

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

    # 从环境变量获取日志格式，默认 text（开发友好）
    log_format = os.getenv("LOG_FORMAT", "text").lower()
    datefmt = "%Y-%m-%d %H:%M:%S"

    if log_format == "json":
        # JSON 格式（生产环境）
        formatter = JsonFormatter(datefmt=datefmt)
    else:
        # 纯文本格式（开发环境）
        formatter = TextFormatter(datefmt=datefmt)

    # 控制台 Handler（始终启用，输出到 stdout 更直观）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件 Handler（仅在 JSON 模式或 INFO 及以上级别启用）
    if log_format == "json" or log_level in ("INFO", "WARNING", "ERROR"):
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
