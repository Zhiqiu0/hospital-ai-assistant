"""
真 PostgreSQL 测试专用 fixtures（tests_pg/ 独立 conftest）

⚠️ 为什么单独一个目录 + 单独 conftest：
  tests/conftest.py 在 import 期把 sqlalchemy 的 JSONB 全局替换成 JSON
  （SQLite 不支持 JSONB）。那个 monkeypatch 是「进程级、import 即生效」的，
  一旦和真 PG 测试跑在同一个 pytest 进程里，患者 profile / qc_rules keywords
  这些 JSONB 字段会退化成普通 JSON，真 PG 上的行为（序列化/类型/搬迁 SQL）
  就永远测不到了。所以本目录必须用 `pytest tests_pg/` 单独一次调用运行，
  绝不能和 tests/ 混在同一进程。

设计要点：
  1. 必须显式提供PG_TEST_DATABASE_URL，且只允许本机地址，建唯一一次性测试库：
     先连默认postgres维护库CREATE，测完仅DROP本次创建的随机库名。
     全程绝不碰开发/生产库 medassist 里的任何数据。
  2. 劫持 app.database.engine → 指向测试库。被测脚本（init_db / alembic_guard）
     都是 `from app.database import engine`，
     只要在它们被 import 之前把 app.database.engine 换掉，它们操作的就是测试库。
     alembic 本体走子进程 + DATABASE_URL 环境变量（见 run_alembic_subprocess）。
     真实开发库 engine 是惰性创建（create_async_engine 不会立即连接），
     被换掉后从不发起任何查询，开发库零影响。
  3. PG 连不上（别人机器没起 postgres / asyncpg 没装）→ 整体 skip，
     不让没有 PG 的环境测试变红。默认 `pytest -q`（testpaths=tests）
     根本不会进入本目录，完全不受影响。
"""

import asyncio
import os as _os
from uuid import uuid4

import pytest
import pytest_asyncio

# 真PG仅允许显式测试库；其余配置与SQLite测试一样，禁止继承业务.env或外部凭据。
from test_support import isolate_external_services
isolate_external_services()

# CI依赖安装问题必须失败；本地未安装可选PG驱动时保留跳过语义。
if _os.environ.get('CI', '').lower() == 'true':
    import asyncpg
else:
    asyncpg = pytest.importorskip("asyncpg")

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 明确选择测试服务，不从业务.env兜底；拒绝远端必须发生在任何连接之前。
_target = _os.environ.get('PG_TEST_DATABASE_URL')
_TARGET_CONFIGURED = bool(_target)
if not _target:
    if _os.environ.get('CI', '').lower() == 'true':
        raise pytest.UsageError('CI必须配置PG_TEST_DATABASE_URL以执行真实PG测试')
    # 仅为模型/迁移导入提供合法URL结构；session夹具会skip，绝不连接此占位地址。
    _target = 'postgresql+asyncpg://test:test@127.0.0.1:1/postgres'
try:
    _real_url = make_url(_target)
except Exception:
    raise pytest.UsageError('PG_TEST_DATABASE_URL格式不合法') from None
if (_real_url.get_backend_name() != 'postgresql'
        or _real_url.host not in {'localhost', '127.0.0.1', '::1'} or _real_url.query):
    raise pytest.UsageError('PG测试仅允许显式本机PostgreSQL目标，不允许远端或连接覆盖参数')

# 并行测试彼此隔离，绝不先删一个可能属于其他进程的固定库。
TEST_DB_NAME = f'medassist_pgtest_{uuid4().hex[:12]}'

# asyncpg 原生直连参数（不带 sqlalchemy 的 +asyncpg 驱动后缀）
_pg_conn_kwargs = dict(
    user=_real_url.username,
    password=_real_url.password,
    host=_real_url.host or "localhost",
    port=_real_url.port or 5432,
)

# 测试库的 sqlalchemy 异步 URL（换库名 + 强制 asyncpg 驱动）
_test_url = _real_url.set(database=TEST_DB_NAME, drivername="postgresql+asyncpg")
# 在任何app模块导入前，连模块级独立连接工厂也只准看到本次测试库。
_os.environ['DATABASE_URL'] = _test_url.render_as_string(hide_password=False)

# 建库失败（PG 不可用）时记录 skip 原因；非 None 即触发 skip
_SKIP_REASON: str | None = None
_DATABASE_CREATED = False  # 仅清理本进程实际成功创建的随机库


async def _create_test_db() -> None:
    """只创建本次唯一库；连接有界，CI不可用时必须失败而非全部跳过。"""
    global _DATABASE_CREATED
    conn = await asyncpg.connect(database="postgres", timeout=10, **_pg_conn_kwargs)
    try:
        # 建库/删库不能在事务里，asyncpg 默认 autocommit，直接 execute 即可
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
        _DATABASE_CREATED = True  # close失败仍必须清理已经创建的数据库
    finally:
        await conn.close()


async def _drop_test_db() -> None:
    """测完拆库：先踢掉测试库上残留连接，再 DROP DATABASE。"""
    conn = await asyncpg.connect(database="postgres", timeout=10, **_pg_conn_kwargs)
    try:
        # DROP DATABASE 要求目标库无活动连接，先强制断开
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            TEST_DB_NAME,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
    finally:
        await conn.close()


# 到测试执行阶段才建库：导入或收集失败时尚无数据库副作用，清理钩子已注册。
@pytest.fixture(scope='session', autouse=True)
def _ensure_test_database():
    """先建唯一测试库；本地未启动PG时跳过，CI服务故障必须失败。"""
    global _SKIP_REASON
    if not _TARGET_CONFIGURED:
        pytest.skip('未配置PG_TEST_DATABASE_URL，跳过独立PG测试')
    try:
        asyncio.run(_create_test_db())
    except Exception as exc:
        _SKIP_REASON = f'PostgreSQL测试服务不可用：{type(exc).__name__}'
        if _os.environ.get('CI', '').lower() == 'true':
            pytest.fail(_SKIP_REASON, pytrace=False)
        pytest.skip(_SKIP_REASON)

# ── 劫持 app.database.engine → 测试库 ─────────────────────────────────────────
# 必须在 init_db / alembic_guard 被 import 之前完成。
# create_async_engine 惰性，不会立刻连库；即使 PG 不可用也能安全构建对象。
import app.database as _db  # noqa: E402

_test_engine = create_async_engine(_test_url.render_as_string(hide_password=False))
_db.engine = _test_engine
_db.AsyncSessionLocal = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)

# ── 导入全部 model，保证 Base.metadata 表结构完整 ─────────────────────────────
# create_all 用的是全局 Base.metadata；生产运行时 app 会 import 全部 model，
# 这里复刻同样的完整性，避免 create_all 漏建被 FK 引用的表。
import app.models.user            # noqa: E402,F401
import app.models.patient         # noqa: E402,F401
import app.models.encounter       # noqa: E402,F401
import app.models.medical_record  # noqa: E402,F401
import app.models.config          # noqa: E402,F401  含 QCRule
import app.models.audit_log       # noqa: E402,F401
import app.models.revoked_token   # noqa: E402,F401
import app.models.inpatient       # noqa: E402,F401
import app.models.imaging         # noqa: E402,F401
import app.models.lab_report      # noqa: E402,F401
import app.models.ai_feedback     # noqa: E402,F401
from app.models.voice_record import VoiceRecord  # noqa: E402,F401

from app.database import Base  # noqa: E402  # 此时拿到的 metadata 已完整


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    """整个 session 跑完拆库：先 dispose 测试 engine 归还连接，再 DROP DATABASE。

    用 pytest 同步钩子 + asyncio.run，避开 session 级 async fixture 与
    function 级 event loop 的作用域冲突。
    """
    async def _teardown():
        try:
            await _test_engine.dispose()
        except Exception:
            pass
        await _drop_test_db()

    # 即使建库后的连接关闭失败，也要拆掉已创建的库；未创建则绝不删库。
    if not _DATABASE_CREATED:
        return
    try:
        asyncio.run(_teardown())
    except Exception as exc:
        # 随机库没有下一轮预清理兜底；保留原有失败码，绝不能把残留报成成功。
        if session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        message = f'PG测试库清理失败：{TEST_DB_NAME}（{type(exc).__name__}），需检查并清理本次测试库'
        reporter = session.config.pluginmanager.getplugin('terminalreporter')
        if reporter is not None:
            reporter.write_sep('!', message, red=True)
        else:
            import warnings
            warnings.warn(pytest.PytestWarning(message), stacklevel=2)


@pytest_asyncio.fixture
async def empty_pg():
    """空测试库：每个用例前把 public schema 清空重建，得到全新空库。

    面向「从零建库」类测试（alembic 基线 / 守卫）。
    DROP SCHEMA CASCADE + CREATE SCHEMA 是 PG 里最干净的整库重置手段。
    """
    if _SKIP_REASON is not None:
        pytest.skip(_SKIP_REASON)

    async with _test_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    try:
        yield _test_engine
    finally:
        # 用例结束 dispose：下个用例（新 event loop）重新建连接，
        # 避免 asyncpg 连接跨 event loop 复用报错
        await _test_engine.dispose()


@pytest_asyncio.fixture
async def pg_with_tables(empty_pg):
    """在空库基础上 create_all 建好全部业务表，面向 JSONB 真实行为测试。"""
    async with _test_engine.begin() as conn:
        # gen_random_uuid 等来自 pgcrypto，部分默认值可能用到，先装上兜底
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        await conn.run_sync(Base.metadata.create_all)
    yield _test_engine


# ── alembic 子进程工具（2026-08-12 迁移单通道收口）───────────────────────────
# alembic/env.py 用 asyncio.run 跑迁移，在 pytest-asyncio 的 event loop 里
# 直接调 alembic.command 会撞"loop already running"——统一走子进程，
# 用 DATABASE_URL 环境变量把子进程指向一次性测试库（settings 读 env 优先）。
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
# 子进程用同步风格 URL（env.py 会自己换 asyncpg 驱动）
TEST_SYNC_URL = _test_url.set(drivername="postgresql").render_as_string(hide_password=False)


def run_alembic_subprocess(*args: str) -> subprocess.CompletedProcess:
    """在 backend 目录下以子进程跑 `python -m alembic <args>`，指向测试库。"""
    env = {**_os.environ, "DATABASE_URL": TEST_SYNC_URL}
    return subprocess.run(
        [sys.executable, "-m", "test_support", "-m", "alembic", *args],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=180,
    )


def run_guard_subprocess() -> subprocess.CompletedProcess:
    """子进程跑 alembic_guard.py（stamp 守卫），指向测试库。"""
    env = {**_os.environ, "DATABASE_URL": TEST_SYNC_URL}
    return subprocess.run(
        [sys.executable, "-m", "test_support", "alembic_guard.py"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120,
    )


@pytest_asyncio.fixture
async def alembic_pg(empty_pg):
    """空库 + `alembic upgrade head` 建好全部表——迁移单通道的正规建库路径。"""
    result = run_alembic_subprocess("upgrade", "head")
    assert result.returncode == 0, (
        f"alembic upgrade head 失败:\n{result.stdout}\n{result.stderr}"
    )
    # 建库后先清一次连接池：上一个用例（另一个 event loop）可能遗留池化连接，
    # 被本用例捞到会报 asyncpg "attached to a different loop"（CI 踩过）。
    await empty_pg.dispose()
    yield empty_pg
