"""
init_db.py 真 PG 测试（盲区 #2：直改生产 schema 的脚本零测试）

历史：本测试首次在空 PG 库上跑 init_db.init() 时，暴露出一个此前无人发现的
真实缺陷——qc_rules 的种子 INSERT 引用了 QCRule schema 重构后已不存在的
`condition` 列、且漏了 NOT NULL 的 rule_code。由于所有种子在同一 session 事务里，
这条一挂 → 科室/admin/doctor01/模板整批回滚 → 全新部署一条种子都进不去。
（生产早在重构前就 seed 过，所以没被发现，只有从零部署才会踩。）

修复（2026-07）：init_db.py 删除了那段已被质控 Rubric 引擎取代的旧 qc_rules 种子。
本测试现在如实验证「修好后的正确行为」：init() 成功建表 + 种子全部落库 + 幂等。
"""

import pytest

import init_db  # noqa: E402  # conftest 已把 app.database.engine 换成一次性测试库
from sqlalchemy import text


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


async def test_init_creates_tables_and_seeds(empty_pg):
    """全新库上 init() 应：建表成功 + 种子全部落库（4 科室 + admin + doctor01）。"""
    engine = empty_pg
    await init_db.init()

    # 业务表建出来
    for tbl in ("users", "departments", "patients", "qc_rules", "prompt_templates"):
        assert await _table_exists(engine, tbl), f"init() 后表 {tbl} 未建出"

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


async def test_init_is_idempotent(empty_pg):
    """再跑一次 init() 不重复插种子、不报错（users 已存在则跳过播种）。"""
    engine = empty_pg
    await init_db.init()
    await init_db.init()  # 第二次应 no-op（内部 count>0 跳过）

    # 科室/用户数量不翻倍
    assert await _scalar(engine, "SELECT COUNT(*) FROM departments") == 4
    assert await _scalar(engine, "SELECT COUNT(*) FROM users WHERE username='admin'") == 1
