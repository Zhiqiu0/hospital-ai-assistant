"""
测试公共 fixtures
- async_db：每个测试用例独立的 SQLite 内存数据库 session
"""
import pytest
import pytest_asyncio

# SQLite 不支持 JSONB，测试时替换为 JSON（必须在 model 导入之前）
import sqlalchemy.dialects.postgresql as _pg
from sqlalchemy import JSON as _JSON
_pg.JSONB = _JSON  # type: ignore

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
