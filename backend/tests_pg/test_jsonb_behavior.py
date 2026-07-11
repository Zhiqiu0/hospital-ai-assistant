"""
JSONB 真实行为测试（盲区 #3）

tests/conftest.py 把 JSONB 全局降级成 JSON 来适配 SQLite，导致 patients.profile、
qc_rules keywords 等字段在「真 PG 上的序列化/反序列化/类型」从没被测过——历史上
qc_rules keywords 的 TEXT/JSONB 事故就是这么漏的。本文件用真 PG + ORM 往返验证。

覆盖：
  - patients.profile（JSONB）：写入嵌套 dict、读回、部分更新，断言类型/结构保真
  - qc_rules.keywords（JSON 列，PG 上以 json/jsonb 存）：写 list、读回，
    断言拿回来是 list 不是 str（历史事故点）
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.patient import Patient
from app.models.config import QCRule


def _session_factory(engine):
    """基于测试库 engine 现造一个 session 工厂（不依赖全局单例）。"""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_patient_profile_jsonb_nested_roundtrip(pg_with_tables):
    """嵌套 dict 写入 JSONB → 读回结构/类型完全保真，且支持部分更新。"""
    Session = _session_factory(pg_with_tables)

    pid = str(uuid.uuid4())
    profile = {
        "past_history": {
            "value": "高血压5年",
            "updated_at": "2026-07-11T10:00:00",
            "updated_by": "doc_001",
        },
        "allergy_history": {"value": "青霉素过敏", "updated_at": None, "updated_by": None},
        # 混入不同 JSON 类型，验证 PG JSONB 反序列化后的 Python 类型
        "meta": {"count": 3, "flag": True, "tags": ["a", "b"]},
    }

    async with Session() as s:
        s.add(Patient(id=pid, name="张三", profile=profile))
        await s.commit()

    # 读回：JSONB 应还原成等价的嵌套 dict（不是字符串）
    async with Session() as s:
        p = (await s.execute(select(Patient).where(Patient.id == pid))).scalar_one()
        assert isinstance(p.profile, dict), "profile 读回应为 dict 而非 str"
        assert p.profile["past_history"]["value"] == "高血压5年"
        assert p.profile["allergy_history"]["updated_at"] is None
        # JSON 数值/布尔/数组类型保真
        assert p.profile["meta"]["count"] == 3
        assert p.profile["meta"]["flag"] is True
        assert p.profile["meta"]["tags"] == ["a", "b"]
        assert isinstance(p.profile["meta"]["tags"], list)

    # 部分更新：整体替换一个新 dict（ORM JSONB 字段整体赋值语义）
    async with Session() as s:
        p = (await s.execute(select(Patient).where(Patient.id == pid))).scalar_one()
        new_profile = dict(p.profile)
        new_profile["past_history"] = {
            "value": "高血压10年",
            "updated_at": "2026-07-12T09:00:00",
            "updated_by": "doc_002",
        }
        p.profile = new_profile
        await s.commit()

    async with Session() as s:
        p = (await s.execute(select(Patient).where(Patient.id == pid))).scalar_one()
        assert p.profile["past_history"]["value"] == "高血压10年"
        # 未改动的字段仍在
        assert p.profile["allergy_history"]["value"] == "青霉素过敏"


async def test_qc_rules_keywords_is_list_not_str(pg_with_tables):
    """qc_rules.keywords 写 list、读回仍是 list（不是 str）——历史事故点回归。"""
    Session = _session_factory(pg_with_tables)

    rid = str(uuid.uuid4())
    keywords = ["主诉", "chief complaint", "C/O"]
    indication = ["高血压", "糖尿病"]

    async with Session() as s:
        s.add(
            QCRule(
                id=rid,
                rule_code="TEST_KW_01",
                name="关键词类型回归",
                rule_type="completeness",
                keywords=keywords,
                indication_keywords=indication,
            )
        )
        await s.commit()

    async with Session() as s:
        r = (await s.execute(select(QCRule).where(QCRule.id == rid))).scalar_one()
        # 核心断言：拿回来必须是 list，绝不能退化成 JSON 字符串
        assert isinstance(r.keywords, list), f"keywords 应为 list，实际 {type(r.keywords)}"
        assert r.keywords == keywords
        assert isinstance(r.indication_keywords, list)
        assert r.indication_keywords == indication


async def test_qc_rules_keywords_empty_list_and_null(pg_with_tables):
    """边界：keywords 存空 list / 不设置(None)，读回类型分别为 list / None，不串味。"""
    Session = _session_factory(pg_with_tables)

    rid_empty = str(uuid.uuid4())
    rid_null = str(uuid.uuid4())
    async with Session() as s:
        s.add(QCRule(id=rid_empty, rule_code="TEST_KW_EMPTY", name="空列表", keywords=[]))
        s.add(QCRule(id=rid_null, rule_code="TEST_KW_NULL", name="未设置", keywords=None))
        await s.commit()

    async with Session() as s:
        r_empty = (await s.execute(select(QCRule).where(QCRule.id == rid_empty))).scalar_one()
        r_null = (await s.execute(select(QCRule).where(QCRule.id == rid_null))).scalar_one()
        assert r_empty.keywords == [] and isinstance(r_empty.keywords, list)
        assert r_null.keywords is None
