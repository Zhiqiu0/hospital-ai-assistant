"""
测试公共 fixtures
- async_db：每个测试用例独立的 SQLite 内存数据库 session

⚠️ 启动顺序很关键，**所有改动必须保留以下顺序**：
  1) 注入 DATABASE_URL 环境变量（在 import app.* 之前）
  2) JSONB → JSON 黑魔法（SQLite 不支持 JSONB，且必须在 model 导入前生效）
  3) 再 import app.database / app.models / 业务代码

这样做的关键效果：app.database.engine 和 AsyncSessionLocal 一开始就是 SQLite
内存——audit_service / task_logger 等 module-level 直接 import 的 AsyncSessionLocal
也都指向 SQLite，不会真的写到开发 PostgreSQL（Audit Round 4 G8）。
"""
# Step 1: 在 app.config / app.database 加载之前注入测试 DATABASE_URL
import os as _os
_os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# 缺省 SECRET_KEY 也兜底，避免 settings 校验失败
_os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
# ORTHANC_PASSWORD 在 config.py 是必填（无默认值），生产无 .env 启动会失败；
# 测试不实际连 Orthanc，但 settings import 期间会校验，所以兜底一个测试占位值。
_os.environ.setdefault("ORTHANC_PASSWORD", "test-orthanc-password-not-for-production")

import pytest
import pytest_asyncio

# Step 2: SQLite 不支持 JSONB，测试时替换为 JSON（必须在 model 导入之前）
import sqlalchemy.dialects.postgresql as _pg
from sqlalchemy import JSON as _JSON
_pg.JSONB = _JSON  # type: ignore

# Step 3: 现在 import app.* 才安全
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.database import Base

# 导入所有 model，确保 metadata 包含完整表结构
import app.models.user          # noqa
import app.models.patient       # noqa
import app.models.encounter     # noqa
import app.models.medical_record  # noqa
import app.models.revoked_token   # noqa
import app.models.inpatient       # noqa  # 含 VitalSign / ProblemItem
import app.models.imaging         # noqa  # 含 ImagingStudy / ImagingReport

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def async_db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
