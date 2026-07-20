"""
SQLAlchemy 基础模型定义

所有数据模型共享同一个 Base，使用 SQLAlchemy 2.0 声明式 ORM。
"""

from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass


class Base(DeclarativeBase):
    """
    所有 ORM 模型的基类
    
    使用 SQLAlchemy 2.0 的 DeclarativeBase 声明式基类。
    所有模型（User、Note、ChatSession 等）都继承此基类。
    """
    pass
