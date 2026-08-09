"""
Alembic 迁移环境（异步引擎适配）

- 复用 app.db.database 的 DATABASE_URL（环境变量驱动，避免配置双份漂移）
- 目标元数据来自 app.models（导入即注册全部表）
- 迁移使用独立引擎（NullPool + 用完即 dispose）：
  应用启动时 init_db 会在线程中调用本模块（asyncio.run），
  若复用应用级引擎会把连接绑定到错误的 event loop，故不可复用。
"""

import asyncio
from logging.config import fileConfig

# 与 main.py 一致：CLI 运行（alembic revision/upgrade）时不经过 dotenv，
# 必须先加载 .env，否则 MYSQL_* 读到默认值
from dotenv import load_dotenv

load_dotenv()

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.db.database import DATABASE_URL
from app.models import Base  # 导入即注册所有模型表

# alembic.ini 中的日志配置
config = context.config

# 数据库 URL：统一使用数据库模块的配置（env 变量驱动）
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL，不连接数据库"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：使用独立异步引擎（NullPool），迁移结束后立即释放"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在线模式入口（Alembic 同步入口，内部桥接异步）"""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
