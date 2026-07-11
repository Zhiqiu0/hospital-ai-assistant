"""
schema_compat.apply_schema_compatibility 真 PG 测试（盲区 #2）

apply_schema_compatibility 负责两件 PG 专属的事：
  1. 一堆 ADD COLUMN IF NOT EXISTS / ALTER（inquiry_inputs 扩展列、影像 UID 等）
  2. 患者档案 TEXT→JSONB 的一次性数据搬迁：把老的 profile_* 扁平 TEXT 列的值
     用 jsonb_build_object 组装进新的 profile JSONB 字段（仅当 profile 为空/NULL）

覆盖：
  - 幂等：连跑多次不报错
  - 搬迁逻辑正确：造一条 profile_past_history 有值、profile 为空的患者，
    跑 compat 后断言值进了 profile JSONB 的 past_history.value；且第二次跑不再改动
"""

import uuid

from app.schema_compat import apply_schema_compatibility  # noqa: E402  # engine 已被 conftest 换成测试库
from sqlalchemy import text


async def _scalar(engine, sql: str, params: dict | None = None):
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params or {})
        return result.scalar()


async def test_apply_is_idempotent(empty_pg):
    """空库上连跑三次 apply_schema_compatibility 不报错（幂等）。"""
    await apply_schema_compatibility()
    await apply_schema_compatibility()
    await apply_schema_compatibility()

    # profile 列应已建出且为 jsonb
    dtype = await _scalar(
        empty_pg,
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name='patients' AND column_name='profile'",
    )
    assert dtype == "jsonb", f"patients.profile 应为 jsonb，实际 {dtype}"


async def test_profile_text_to_jsonb_migration(empty_pg):
    """老 profile_past_history TEXT 值应被搬迁进 profile JSONB 的 past_history.value。"""
    engine = empty_pg

    # 第一次：建表 + 加列（此时没有患者数据）
    await apply_schema_compatibility()

    # 造一条老患者：profile_past_history 有值、profile 留空（NULL）
    # 显式给 id（不依赖 pgcrypto 的 gen_random_uuid）
    pid = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO patients "
                "(id, name, is_from_his, is_deleted, profile_past_history, created_at, updated_at) "
                "VALUES (:id, '张三', false, false, :ph, NOW(), NOW())"
            ),
            {"id": pid, "ph": "高血压5年"},
        )

    # 第二次：触发 TEXT→JSONB 搬迁（WHERE profile IS NULL OR profile='{}'）
    await apply_schema_compatibility()

    # 断言值已进 JSONB，且结构是 {"past_history": {"value": "高血压5年", ...}}
    val = await _scalar(
        engine,
        "SELECT profile->'past_history'->>'value' FROM patients WHERE id=:id",
        {"id": pid},
    )
    assert val == "高血压5年", f"past_history 未正确搬迁进 JSONB，实际 {val}"

    # 搬迁后 profile 已非空；第三次跑不应再改动（WHERE 条件不再命中）
    updated_at_before = await _scalar(
        engine,
        "SELECT profile->'past_history'->>'updated_at' FROM patients WHERE id=:id",
        {"id": pid},
    )
    await apply_schema_compatibility()
    updated_at_after = await _scalar(
        engine,
        "SELECT profile->'past_history'->>'updated_at' FROM patients WHERE id=:id",
        {"id": pid},
    )
    assert updated_at_before == updated_at_after, "已迁移数据不应被二次搬迁覆盖"
