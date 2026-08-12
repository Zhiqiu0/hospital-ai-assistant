"""alembic 单一真源门禁（2026-08-12 迁移四通道收口的验收测试）。

收口后 alembic 是唯一 schema 通道（migrate.py / schema_compat / init_db 的
create_all 均已删除）。本文件锁住四条不变量：

  1. 空库上 `alembic upgrade head` 一步建成完整 schema——
     模型元数据里的每张表、每个列都必须存在（防基线漏建）
  2. 重复 upgrade 幂等（防后续 revision 违反"必须幂等"铁律）
  3. 基线手写补齐的三样真实生效：pgcrypto / CHECK 约束 / 审计只追加触发器
  4. alembic_guard 守卫：老库（表在但版本缺失）被 stamp 到基线且零 DDL
"""
import pytest
from sqlalchemy import text

from tests_pg.conftest import run_alembic_subprocess, run_guard_subprocess

pytestmark = pytest.mark.asyncio


async def _existing_columns(engine) -> set[tuple[str, str]]:
    """取 public schema 下全部 (表名, 列名)。"""
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public'"
        ))
        return {(t, c) for t, c in rows}


async def test_upgrade_head_builds_full_schema(alembic_pg):
    """空库 upgrade head 后：模型声明的每张表每个列都在（单一真源成立）。"""
    from app.database import Base

    existing = await _existing_columns(alembic_pg)
    missing = [
        (table.name, col.name)
        for table in Base.metadata.sorted_tables
        for col in table.columns
        if (table.name, col.name) not in existing
    ]
    assert not missing, f"alembic 建库缺表/缺列：{missing}"

    # alembic_version 已推进到链头（基线 + 后续常规迁移）
    async with alembic_pg.connect() as conn:
        ver = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert ver == "c20260812adoptidx"


async def test_upgrade_head_is_idempotent(alembic_pg):
    """已在 head 的库再跑一次 upgrade：不报错、版本不变。"""
    result = run_alembic_subprocess("upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr


async def test_alembic_check_no_model_drift(alembic_pg):
    """`alembic check` 空 diff——**"改模型必须写迁移"的真门禁**。

    基线是冻结 DDL 快照（不随模型演进），所以本检查有判别力：
    谁改了 model 却没写配套 revision，这里立刻红灯——否则 CI 全绿、
    生产库（已在 head，upgrade 无事可做）静默缺列，线上随机 500。
    """
    result = run_alembic_subprocess("check")
    assert result.returncode == 0, (
        "模型与迁移链建出的库存在漂移——你改了 model 但没写配套 revision：\n"
        + result.stdout + result.stderr
    )


async def test_baseline_extras_effective(alembic_pg):
    """基线手写三件套真实生效：CHECK 约束 / 审计触发器 / pgcrypto。"""
    async with alembic_pg.connect() as conn:
        # CHECK 约束（身份证 18 位）挡脏数据
        names = (await conn.execute(text(
            "SELECT conname FROM pg_constraint WHERE conname LIKE 'ck_%'"
        ))).scalars().all()
        for expected in (
            "ck_patient_id_card_length", "ck_patient_phone_length",
            "ck_patient_contact_phone_length", "ck_user_phone_length",
        ):
            assert expected in names, f"CHECK 约束 {expected} 未建出"

        # pgcrypto：gen_random_uuid 可用
        assert (await conn.execute(text("SELECT gen_random_uuid()"))).scalar() is not None

    # 审计只追加触发器：UPDATE 必须被数据库拒绝
    async with alembic_pg.begin() as conn:
        await conn.execute(text(
            "INSERT INTO audit_logs (id, action, status, created_at) "
            "VALUES ('audit-t-1', 'test', 'ok', NOW())"
        ))
    with pytest.raises(Exception, match="只追加|append"):
        async with alembic_pg.begin() as conn:
            await conn.execute(text(
                "UPDATE audit_logs SET action='tamper' WHERE id='audit-t-1'"
            ))


async def test_guard_stamps_legacy_db_without_ddl(pg_with_tables):
    """老库场景（create_all 建过表、无 alembic_version）：

    guard 应 stamp 到基线（纯写标记），随后 upgrade head 无事可做。
    """
    engine = pg_with_tables
    # 前置：确实没有 alembic_version（模拟只跑过 migrate.py 的历史库）
    async with engine.connect() as conn:
        assert (await conn.execute(
            text("SELECT to_regclass('public.alembic_version')")
        )).scalar() is None

    result = run_guard_subprocess()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stamp" in result.stdout

    async with engine.connect() as conn:
        ver = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert ver == "b20260812squash"

    # stamp 后 upgrade 幂等通过
    result = run_alembic_subprocess("upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr


async def test_guard_refuses_stamp_when_columns_missing(pg_with_tables):
    """恢复旧备份场景：库缺模型列时 guard 必须 FATAL 拒绝 stamp（防带病打标记）。

    带病 stamp 的后果：upgrade 无事可做、所有工具声称在 head、
    运行期随机 500 且排障无线索——宁可启动失败也不能静默掩盖。
    """
    engine = pg_with_tables
    # 模拟"压缩重置前的旧备份"：砍掉一个后来加的列
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE record_versions DROP COLUMN ai_similarity"))

    result = run_guard_subprocess()
    assert result.returncode != 0, "缺列的库居然通过了 guard 校验"
    assert "拒绝 stamp" in (result.stdout + result.stderr)

    # 确认没有偷偷写入版本标记
    async with engine.connect() as conn:
        has_av = (await conn.execute(
            text("SELECT to_regclass('public.alembic_version')")
        )).scalar()
    assert has_av is None


async def test_guard_noop_on_fresh_and_current_db(alembic_pg):
    """已在新链上的库：guard 什么都不做（不报错、版本不变）。"""
    result = run_guard_subprocess()
    assert result.returncode == 0, result.stdout + result.stderr
    async with alembic_pg.connect() as conn:
        ver = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert ver == "c20260812adoptidx"
