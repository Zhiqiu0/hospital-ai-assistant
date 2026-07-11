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
  1. 只连本地 postgres，建一个「一次性测试库」medassist_pgtest：
     先连默认 postgres 维护库，DROP DATABASE IF EXISTS 再 CREATE，测完 DROP。
     全程绝不碰开发/生产库 medassist 里的任何数据。
  2. 劫持 app.database.engine → 指向测试库。被测的三个脚本
     （init_db / migrate / schema_compat）都是 `from app.database import engine`，
     只要在它们被 import 之前把 app.database.engine 换掉，它们操作的就是测试库。
     真实开发库 engine 是惰性创建（create_async_engine 不会立即连接），
     被换掉后从不发起任何查询，开发库零影响。
  3. PG 连不上（别人机器没起 postgres / asyncpg 没装）→ 整体 skip，
     不让没有 PG 的环境测试变红。默认 `pytest -q`（testpaths=tests）
     根本不会进入本目录，完全不受影响。
"""

import asyncio
import os as _os

import pytest
import pytest_asyncio

# Settings 里 secret_key / orthanc_password 是必填（无默认值），import app.config 即校验。
# 本目录只需真实 DATABASE_URL（连 PG 建测试库），这两个与 PG 测试无关的必填项给测试兜底，
# 否则 CI 环境(只设了 DATABASE_URL/SECRET_KEY)会在 import settings 时因缺 ORTHANC_PASSWORD 挂。
# 必须在 `from app.config import settings` 之前 setdefault。
_os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
_os.environ.setdefault("ORTHANC_PASSWORD", "test-orthanc-password-not-for-production")

# asyncpg 是建库/拆库直连驱动，没装则本目录整体 skip
asyncpg = pytest.importorskip("asyncpg")

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 只 import settings 读取真实开发库 URL——import app.config 不会创建 engine
from app.config import settings

# ── 解析真实开发库连接串 ──────────────────────────────────────────────────────
# 形如 postgresql://medassist:<pwd>@localhost:5432/medassist
_real_url = make_url(settings.database_url)

# 一次性测试库名（与开发库 medassist 隔离，绝不同名）
TEST_DB_NAME = "medassist_pgtest"

# asyncpg 原生直连参数（不带 sqlalchemy 的 +asyncpg 驱动后缀）
_pg_conn_kwargs = dict(
    user=_real_url.username,
    password=_real_url.password,
    host=_real_url.host or "localhost",
    port=_real_url.port or 5432,
)

# 测试库的 sqlalchemy 异步 URL（换库名 + 强制 asyncpg 驱动）
_test_url = _real_url.set(database=TEST_DB_NAME, drivername="postgresql+asyncpg")

# 建库失败（PG 不可用）时记录 skip 原因；非 None 即触发 skip
_SKIP_REASON: str | None = None


async def _create_test_db() -> None:
    """连默认 postgres 维护库，DROP IF EXISTS + CREATE 一次性测试库。"""
    conn = await asyncpg.connect(database="postgres", **_pg_conn_kwargs)
    try:
        # 建库/删库不能在事务里，asyncpg 默认 autocommit，直接 execute 即可
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


async def _drop_test_db() -> None:
    """测完拆库：先踢掉测试库上残留连接，再 DROP DATABASE。"""
    conn = await asyncpg.connect(database="postgres", **_pg_conn_kwargs)
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


# ── import 期尝试建库；连不上则标记整体 skip ──────────────────────────────────
try:
    asyncio.run(_create_test_db())
except Exception as e:  # noqa: BLE001 - 连不上就整体 skip，不细分异常类型
    _SKIP_REASON = f"本地 PostgreSQL 不可用，跳过真 PG 测试：{type(e).__name__}: {e}"

# ── 劫持 app.database.engine → 测试库 ─────────────────────────────────────────
# 必须在 init_db / migrate / schema_compat 被 import 之前完成。
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

    # 建库都失败过就没东西可拆
    if _SKIP_REASON is not None:
        return
    try:
        asyncio.run(_teardown())
    except Exception:
        # 拆库失败不该让整轮测试判定失败，交由下一轮 CREATE 前的 DROP IF EXISTS 兜底
        pass


@pytest_asyncio.fixture
async def empty_pg():
    """空测试库：每个用例前把 public schema 清空重建，得到全新空库。

    面向 init_db / migrate / schema_compat 这类「自己负责建表」的脚本测试。
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
