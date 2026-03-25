import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入所有 model，autogenerate 才能检测完整 schema
from app.database import Base          # noqa
import app.models.user                 # noqa
import app.models.patient              # noqa
import app.models.encounter            # noqa
import app.models.medical_record       # noqa
import app.models.audit_log            # noqa
import app.models.config               # noqa
import app.models.voice_record         # noqa
import app.models.imaging              # noqa
import app.models.lab_report           # noqa
import app.models.revoked_token        # noqa

target_metadata = Base.metadata

# 从 app settings 读取数据库 URL，覆盖 alembic.ini 占位符
from app.config import settings
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
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
    # 确保使用 asyncpg 驱动
    db_url = settings.database_url
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    connectable = create_async_engine(db_url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
