"""
MySQL 数据库配置模块

提供异步 SQLAlchemy 引擎和会话管理：
- 异步引擎（aiomysql）连接池：10 + 20
- per-request 会话依赖注入（get_db）
- 数据库初始化（init_db）：自动建表 + 补列迁移
- UTF-8 MB4 编码
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.logger_handler import logger
from app.models.base import Base

# ========== 数据库连接配置 ==========

# 从环境变量构建数据库 URL（使用 aiomysql 异步驱动）
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "raglearn")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "raglearn")

DATABASE_URL = (
    f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
)

# ========== 异步引擎与会话工厂 ==========

# 异步引擎：连接池 20（最小）+ 30（最大溢出）
# 单个 /chat/query 请求最多打开 4-6 个独立 session，10 并发即可耗尽旧配置（pool=10+20）
# 扩容至 20+30=50，支撑约 15-20 并发用户（需 MySQL max_connections >= 200）
engine = create_async_engine(
    url=DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,       # 连接前 ping 检测，自动重连断开的连接
    pool_recycle=3600,        # 连接回收时间（秒），防止 MySQL 8 小时超时断连
    echo=False,               # 生产环境关闭 SQL 日志
)

# 异步会话工厂
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # commit 后不自动过期，允许延迟访问属性
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入：提供 per-request 的异步数据库会话
    
    每个请求获取独立的 AsyncSession，请求结束后自动关闭。
    自动处理 commit 和 rollback：
    - 正常执行完毕自动 commit（如果路由未显式 commit）
    - 发生异常自动 rollback
    
    注意：如果路由已显式 commit，此处的 commit 是空操作（autobegin 新事务），
    不会影响已持久化的数据。commit 失败时仅记录日志，不传播异常，
    因为此时响应已构建，传播异常无意义且可能干扰已提交的数据。
    
    Yields:
        AsyncSession: 异步数据库会话
    """
    async with async_session_factory() as session:
        try:
            yield session
            try:
                await session.commit()
            except Exception as commit_err:
                # 路由可能已显式 commit（如批量操作），此处 commit 是 autobegin 空事务。
                # 如果空事务 commit 失败（连接断开等），已提交的数据不受影响。
                # 仅记录日志，不传播异常。
                logger.warning(f"get_db auto-commit 异常（已提交数据不受影响）: {commit_err}")
                try:
                    await session.rollback()
                except Exception:
                    pass
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    初始化数据库表结构
    
    执行流程：
    1. create_all: 创建所有不存在的表
    2. _migrate_columns: 自动补列迁移（检测模型中新增的列并 ALTER TABLE ADD COLUMN）
    
    注意：这是轻量级迁移方案，不支持删列、改类型等复杂操作。
    复杂迁移建议使用 Alembic。
    """
    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        logger.info("数据库表结构初始化完成")
    
    # 执行自动补列迁移
    await _migrate_columns()


async def _migrate_columns() -> None:
    """
    自动补列迁移
    
    对比 SQLAlchemy 模型定义的列与数据库实际表的列，
    自动执行 ALTER TABLE ADD COLUMN 添加缺失的列。
    
    限制：
    - 只能添加新列，不能修改或删除已有列
    - 新增的非空列必须有默认值，否则可能导致现有查询异常
    """
    async with engine.begin() as conn:
        # 获取数据库检查器
        def get_table_columns(sync_conn):
            inspector = inspect(sync_conn)
            return {
                table_name: {col["name"] for col in inspector.get_columns(table_name)}
                for table_name in inspector.get_table_names()
            }
        
        existing_columns = await conn.run_sync(get_table_columns)
        
        # 遍历所有模型，检查是否有缺失的列
        for table in Base.metadata.tables.values():
            table_name = table.name
            
            if table_name not in existing_columns:
                # 表不存在（应该已被 create_all 创建）
                continue
            
            existing_cols = existing_columns[table_name]
            
            for column in table.columns:
                if column.name not in existing_cols:
                    # 构建 ADD COLUMN 语句
                    col_type = column.type.compile(engine.dialect)
                    nullable = "NULL" if column.nullable else "NOT NULL"
                    default = ""
                    if column.default is not None:
                        if hasattr(column.default, 'arg'):
                            default = f" DEFAULT '{column.default.arg}'"
                    elif column.server_default is not None:
                        default = f" DEFAULT {column.server_default.arg}"
                    
                    sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{column.name}` {col_type} {nullable}{default}"
                    
                    try:
                        await conn.execute(text(sql))
                        logger.info(f"自动补列: {table_name}.{column.name}")
                    except Exception as e:
                        logger.error(f"补列失败: {table_name}.{column.name} - {e}")


async def close_db() -> None:
    """
    关闭数据库连接池
    
    在应用关闭时调用，释放所有数据库连接资源。
    """
    await engine.dispose()
    logger.info("数据库连接池已关闭")
