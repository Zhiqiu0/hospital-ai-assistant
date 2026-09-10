# -*- coding: utf-8 -*-
"""质控规则覆盖度披露（2026-09-10 收敛轮审计）。

抓的问题：住院"日常病程 18 分""上级医师查房 5 分"两个大项 deduction_rules
至今为空——course_record / senior_round 跑质控必然"零扣分 = 100 分"，前端
显示"质控通过（100 分 甲级）"，给医生虚假背书（生产实测：一句"患者今日
无特殊。"的日常病程拿 100 分零问题）。日常病程是住院期间产量最大的文书，
虚假的满分比没有质控更误导。

两层防线：
  ① _ZERO_RULE_RECORD_TYPES 声明与 rubric 实际状态的一致性——用空病历探针
     守着：有规则覆盖的类型，空病历必被扣分；零覆盖的类型恒 100。
     将来某类型实装了规则而没从声明里移除（或反之），这里当场红。
  ② SSE 事件必须把"仅供参考"披露出去：rules_covered 字段 + done 摘要文案，
     零覆盖类型不允许出现"质控通过"字样。
"""
from datetime import datetime

import pytest

from app.models.encounter import Encounter
from app.models.patient import Patient
from app.services.ai._qc_rubric import (
    _INPATIENT_RECORD_TYPES,
    _ZERO_RULE_RECORD_TYPES,
    _select_rubric,
    has_rule_coverage,
)
from app.services.qc_engine.checker import build_context
from app.services.qc_engine.scorer import score

# 内容刻意空洞：任何有真实规则的类型都该在它身上扣出分来
_EMPTY_RECORD = "患者今日无特殊。"


# ── ① 声明与 rubric 实际状态的一致性 ─────────────────────────────────────

@pytest.mark.parametrize(
    "record_type", sorted(_INPATIENT_RECORD_TYPES | {"outpatient", "emergency"})
)
def test_零规则声明与空病历探针一致(record_type):
    """空病历零扣分 ⟺ 该类型在零规则声明里。

    实装了日常病程/上级查房规则后，这条会红——届时把该类型从
    _ZERO_RULE_RECORD_TYPES 移除即可，披露自动消失。"""
    rubric = _select_rubric(record_type)
    ctx = build_context(_EMPTY_RECORD, record_type=record_type)
    report = score(rubric, ctx)

    declared_zero = record_type in _ZERO_RULE_RECORD_TYPES
    actually_zero = len(report.deductions) == 0
    assert declared_zero == actually_zero, (
        f"{record_type}: 声明零规则={declared_zero}，空病历实际扣分数="
        f"{len(report.deductions)}——声明与 rubric 实际状态漂移了"
    )


def test_has_rule_coverage_与声明一致():
    assert not has_rule_coverage("course_record")
    assert not has_rule_coverage("senior_round")
    assert has_rule_coverage("admission_note")
    assert has_rule_coverage("outpatient")
    assert has_rule_coverage(None)  # 默认门诊


# ── ② SSE 事件披露 ───────────────────────────────────────────────────────

async def _mk_encounter(db) -> str:
    p = Patient(name="覆盖度披露", gender="male")
    db.add(p)
    await db.flush()
    e = Encounter(patient_id=p.id, doctor_id="doc-1", visit_type="inpatient",
                  visited_at=datetime.now())
    db.add(e)
    await db.commit()
    return e.id


async def _run_qc(async_db, monkeypatch, record_type: str) -> dict:
    """跑一次 quick-qc 流（LLM 打桩为空建议），按事件类型收拢。"""
    from app.schemas.ai_request import QuickQCRequest
    from app.services.ai import qc_stream_service

    async def _fake_llm(*a, **k):
        return {"issues": []}

    monkeypatch.setattr(qc_stream_service.llm_client, "chat_json_stream", _fake_llm)

    enc_id = await _mk_encounter(async_db)
    req = QuickQCRequest(content=_EMPTY_RECORD, record_type=record_type,
                         encounter_id=enc_id)
    events = [e async for e in qc_stream_service.run_quick_qc_stream(async_db, req)]
    return {e["type"]: e for e in events}


@pytest.mark.asyncio
async def test_零规则类型必须披露仅供参考(async_db, monkeypatch):
    by_type = await _run_qc(async_db, monkeypatch, "course_record")

    assert by_type["rule_issues"]["rules_covered"] is False
    done = by_type["done"]
    assert done["rules_covered"] is False
    assert "暂未覆盖" in done["summary"], f"披露文案缺失：{done['summary']}"
    # 100 分不许冒充结论
    assert "质控通过" not in done["summary"]


@pytest.mark.asyncio
async def test_有规则类型不受披露影响(async_db, monkeypatch):
    by_type = await _run_qc(async_db, monkeypatch, "admission_note")

    assert by_type["rule_issues"]["rules_covered"] is True
    done = by_type["done"]
    assert done["rules_covered"] is True
    assert "暂未覆盖" not in done["summary"]
