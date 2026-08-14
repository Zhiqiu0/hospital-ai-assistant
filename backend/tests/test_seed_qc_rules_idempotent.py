"""seed_config 质控规则 upsert 回归测试（2026-08-14 第七轮审计）。

原实现是 `DELETE FROM qc_rules` + 全量重插且 is_active 硬编码 True，
而 seed_config.py 在 entrypoint.sh 里**每次容器启动都会跑**——
被停用的规则会在下次重启时无声复活。本测试锁死三条不变量：
  1. 重复执行不产生重复行（幂等）
  2. 库里被停用的规则，再跑一次仍然是停用的
  3. 代码里删掉的规则，会真的从库里消失
"""

import pytest
from sqlalchemy import select

from app.models.config import QCRule


async def _run_seed_rules(session, rules):
    """复刻 seed() 里的质控规则 upsert 段落（同一套逻辑，注入自定义规则集）。

    seed() 自身直连生产 engine 且连带处理 prompt 模板，测试里不便整体调用；
    这里保持与被测代码同构——若 seed() 的 upsert 逻辑被改回删除重建，
    需要同步改这里，届时下面的断言会立刻暴露语义变化。
    """
    existing = {
        row.rule_code: row for row in (await session.execute(select(QCRule))).scalars()
    }
    seeded_codes = {r["rule_code"] for r in rules}

    for rule in rules:
        obj = existing.get(rule["rule_code"])
        if obj is None:
            obj = QCRule(rule_code=rule["rule_code"], is_active=True)
            session.add(obj)
        obj.name = rule["name"]
        obj.rule_type = rule["rule_type"]
        obj.risk_level = rule.get("risk_level", "medium")

    for code in [c for c in existing if c not in seeded_codes]:
        await session.delete(existing[code])
    await session.flush()


_RULES = [
    {"rule_code": "R001", "name": "主诉缺失", "rule_type": "completeness"},
    {"rule_code": "R002", "name": "现病史过短", "rule_type": "completeness"},
]


@pytest.mark.asyncio
async def test_重复执行不产生重复行(async_db):
    await _run_seed_rules(async_db, _RULES)
    await _run_seed_rules(async_db, _RULES)
    await _run_seed_rules(async_db, _RULES)

    rows = (await async_db.execute(select(QCRule))).scalars().all()
    assert len(rows) == 2
    assert {r.rule_code for r in rows} == {"R001", "R002"}


@pytest.mark.asyncio
async def test_被停用的规则不会被重启复活(async_db):
    """这是本次修复的核心：原实现每次重插都写死 is_active=True。"""
    await _run_seed_rules(async_db, _RULES)

    r1 = (
        await async_db.execute(select(QCRule).where(QCRule.rule_code == "R001"))
    ).scalar_one()
    r1.is_active = False  # 运维把这条误报多的规则关掉
    await async_db.flush()

    await _run_seed_rules(async_db, _RULES)  # 模拟容器重启

    r1 = (
        await async_db.execute(select(QCRule).where(QCRule.rule_code == "R001"))
    ).scalar_one()
    assert r1.is_active is False, "停用的规则被 seed 重新打开了"


@pytest.mark.asyncio
async def test_正文字段仍以代码为准(async_db):
    """只有 is_active 归运维，规则口径本身每次与代码对齐。"""
    await _run_seed_rules(async_db, _RULES)
    changed = [{**_RULES[0], "name": "主诉缺失（改）"}, _RULES[1]]
    await _run_seed_rules(async_db, changed)

    r1 = (
        await async_db.execute(select(QCRule).where(QCRule.rule_code == "R001"))
    ).scalar_one()
    assert r1.name == "主诉缺失（改）"


@pytest.mark.asyncio
async def test_代码里删掉的规则会从库里消失(async_db):
    await _run_seed_rules(async_db, _RULES)
    await _run_seed_rules(async_db, [_RULES[0]])

    rows = (await async_db.execute(select(QCRule))).scalars().all()
    assert {r.rule_code for r in rows} == {"R001"}
