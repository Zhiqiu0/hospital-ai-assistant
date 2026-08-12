"""
init_db.py 真 PG 测试

2026-08-12 迁移收口后 init_db 只播种子（建表归 alembic 基线）——
本测试用 alembic_pg 夹具（空库 + alembic upgrade head）复刻 entrypoint
的真实顺序：alembic 建表 → init_db 播种子，验证种子全部落库 + 幂等。

工程注意（CI 踩坑）：conftest 的共享 engine 在多用例间会残留上一个
event loop 的池化连接，第二个用例拿到就报 asyncpg
"attached to a different loop"。这里给每个用例造一台**独立 engine**
并 monkeypatch 进 init_db，全程只活在当前 loop，机制上免疫。
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import init_db  # noqa: E402  # conftest 已把 app.database.engine 换成一次性测试库
from tests_pg.conftest import _test_url


@pytest_asyncio.fixture
async def init_engine(alembic_pg, monkeypatch):
    """本用例独占的异步 engine：注入 init_db，测完 dispose。"""
    eng = create_async_engine(_test_url.render_as_string(hide_password=False))
    monkeypatch.setattr(init_db, "engine", eng)
    yield eng
    await eng.dispose()


async def _table_exists(engine, table_name: str) -> bool:
    """查 information_schema 判断某表是否存在于 public schema。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=:t"
            ),
            {"t": table_name},
        )
        return result.scalar() is not None


async def _scalar(engine, sql: str, params: dict | None = None):
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        return result.scalar()


async def test_init_creates_tables_and_seeds(init_engine):
    """alembic 建好表后 init() 应把种子全部落库（4 科室 + admin + doctor01）。"""
    engine = init_engine
    await init_db.init()

    # 业务表由 alembic 基线建出（init_db 不再负责建表）
    for tbl in ("users", "departments", "patients", "qc_rules", "prompt_templates"):
        assert await _table_exists(engine, tbl), f"alembic 基线后表 {tbl} 未建出"

    # 种子落库（不再整批回滚）
    assert await _scalar(engine, "SELECT COUNT(*) FROM departments") == 4
    assert (
        await _scalar(engine, "SELECT role FROM users WHERE username='admin'")
        == "super_admin"
    )
    doctor_dept = await _scalar(
        engine,
        "SELECT d.code FROM users u JOIN departments d ON u.department_id = d.id "
        "WHERE u.username='doctor01'",
    )
    assert doctor_dept == "NEIKE"


async def test_init_is_idempotent(init_engine):
    """再跑一次 init() 不重复插种子、不报错（users 已存在则跳过播种）。"""
    engine = init_engine
    await init_db.init()
    await init_db.init()  # 第二次应 no-op（内部 count>0 跳过）

    # 科室/用户数量不翻倍
    assert await _scalar(engine, "SELECT COUNT(*) FROM departments") == 4
    assert await _scalar(engine, "SELECT COUNT(*) FROM users WHERE username='admin'") == 1
