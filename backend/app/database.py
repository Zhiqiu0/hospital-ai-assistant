"""
数据库连接与会话管理（database.py）

技术栈：SQLAlchemy 2.x 异步引擎 + asyncpg 驱动 + PostgreSQL

提供：
  - engine           : 全局异步连接引擎（连接池）
  - AsyncSessionLocal: 异步 Session 工厂
  - Base             : 所有 ORM Model 的基类
  - get_db()         : FastAPI 依赖注入函数，提供请求级别的数据库会话

连接池配置：
  pool_size=10   : 保持 10 个常驻连接
  max_overflow=20: 高峰期最多额外开 20 个连接（超出后排队等待）
  合计最大 30 个并发连接，适合中型医院的并发量

会话使用说明：
  1. 路由层：通过 Depends(get_db) 注入 session，无需手动管理生命周期
  2. 后台任务：使用 AsyncSessionLocal() 上下文管理器手动管理
     async with AsyncSessionLocal() as db:
         ...
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# ── 数据库 URL 处理 ────────────────────────────────────────────────────────────
# pydantic-settings 读取的是标准 postgresql:// URL，
# asyncpg 驱动要求 postgresql+asyncpg:// 前缀，这里做统一替换
async_db_url = settings.database_url.replace(
    "postgresql://", "postgresql+asyncpg://"
)

# ── 异步引擎 ──────────────────────────────────────────────────────────────────
# echo=settings.app_debug: 开发环境打印 SQL 语句，生产环境关闭（app_debug=False）
# pool_size/max_overflow 仅 PostgreSQL/MySQL 等支持连接池的驱动适用；
# SQLite (含 CI 的 sqlite+aiosqlite:///:memory:) 用 StaticPool，不接受这两个参数
_engine_kwargs: dict = {"echo": settings.app_debug}
if not async_db_url.startswith("sqlite"):
    _engine_kwargs["pool_size"] = 10        # 连接池核心大小
    _engine_kwargs["max_overflow"] = 20     # 超出 pool_size 时最多额外创建的连接数
engine = create_async_engine(async_db_url, **_engine_kwargs)

# ── Session 工厂 ──────────────────────────────────────────────────────────────
# expire_on_commit=False: commit 后 ORM 对象不失效，避免访问属性时触发额外查询
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── ORM 基类 ──────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """所有 ORM Model 的基类，由 SQLAlchemy 2.x DeclarativeBase 提供元数据管理。"""
    pass


# ── FastAPI 依赖 ──────────────────────────────────────────────────────────────

async def get_db():
    """FastAPI 依赖注入函数，为每个请求提供独立的异步数据库会话。

    使用方式：
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...

    会话生命周期：
      - 请求开始时创建 session
      - 路由函数执行完毕（或发生异常）后，finally 块关闭 session
      - 事务提交/回滚由路由层显式调用 db.commit() / db.rollback()

    注意：此函数不自动提交事务，路由层需显式调用 await db.commit()。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            # 确保 session 总是被关闭，释放连接回连接池
            await session.close()
