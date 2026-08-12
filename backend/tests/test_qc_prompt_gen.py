"""QC 提示词标准段生成器测试（2026-08-12 质控双真相源收口）。

覆盖范围：
  - build_qc_standard_block：门急诊/住院两份法定评分表都能渲染，
    含大项名/分值/扣分细则/单项否决/等级判定
  - QC_PROMPT 模板与生成段拼装无 KeyError
  - **打分独立性回归（防止回到"修不到100分"的老问题）**：
    LLM 建议无论返回多少条，grade_score / pass / must_fix_count
    一律只由规则引擎决定，LLM 输出不参与总分。
"""
import pytest

from app.services.ai._qc_prompt_gen import build_qc_standard_block
from app.services.ai.ai_utils import safe_format
from app.services.ai.prompts_qc import QC_PROMPT
from app.services.qc_engine.rubrics.zj_inpatient_2021 import ZJ_INPATIENT_V2021
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023,
)


# ── 标准段生成 ───────────────────────────────────────────────────────────────


def test_outpatient_block_contains_all_items():
    """门急诊标准段：每个大项名和分值都要出现在文本里。"""
    block = build_qc_standard_block(ZJ_OUTPATIENT_EMERGENCY_V2023)
    assert ZJ_OUTPATIENT_EMERGENCY_V2023.name in block
    for item in ZJ_OUTPATIENT_EMERGENCY_V2023.items:
        assert item.name in block
    # 等级判定行（门诊：合格/不合格）
    assert "等级判定" in block


def test_inpatient_block_contains_veto_rules():
    """住院标准段：单项否决规则必须以【单项否决】标记呈现。"""
    block = build_qc_standard_block(ZJ_INPATIENT_V2021)
    has_veto = any(item.veto_rules for item in ZJ_INPATIENT_V2021.items)
    assert has_veto, "住院评分表应含单项否决规则（PDF 备注6）"
    assert "【单项否决】" in block
    assert "不再累积扣分" in block


def test_block_contains_deduction_descriptions():
    """扣分细则描述逐条进入文本（抽查第一个有细则的大项）。"""
    rubric = ZJ_OUTPATIENT_EMERGENCY_V2023
    item = next(i for i in rubric.items if i.deduction_rules)
    block = build_qc_standard_block(rubric)
    for rule in item.deduction_rules:
        assert rule.description in block


def test_qc_prompt_renders_with_standard_block():
    """QC_PROMPT + 生成段拼装：无 KeyError，占位符全部填充。"""
    block = build_qc_standard_block(ZJ_OUTPATIENT_EMERGENCY_V2023)
    prompt = safe_format(
        QC_PROMPT, record_type="门诊病历", content="主诉：发热3天。", standard_block=block
    )
    assert "门诊病历" in prompt
    assert "主诉：发热3天。" in prompt
    assert ZJ_OUTPATIENT_EMERGENCY_V2023.name in prompt
    # 模板里的 JSON 花括号应被 format 还原成单层
    assert '"issues"' in prompt
    assert "{standard_block}" not in prompt


# ── 打分独立性回归（核心保障）────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_issues_never_affect_score(async_db, monkeypatch):
    """LLM 返回一堆问题时，分数/等级/必修数仍与规则引擎结果一致。

    这是"双真相源收口"的安全边界：提示词改了，打分链路一根手指都不能碰。
    """
    from app.schemas.ai_request import QuickQCRequest
    from app.services.ai import qc_stream_service
    from app.services.ai.llm_client import llm_client

    fake_llm_issues = [
        {
            "risk_level": "high",
            "field_name": f"虚构字段{i}",
            "issue_description": "LLM 编的问题",
            "suggestion": "无",
            "score_impact": "0",
        }
        for i in range(5)
    ]

    async def _fake_chat(*_args, **_kwargs):
        return {"issues": fake_llm_issues, "summary": "x", "pass": False}

    monkeypatch.setattr(llm_client, "chat_json_stream", _fake_chat)

    req = QuickQCRequest(
        content="主诉：发热3天。\n现病史：3天前受凉后发热。",
        record_type="outpatient",
    )
    events = [e async for e in qc_stream_service.run_quick_qc_stream(async_db, req)]
    by_type = {e["type"]: e for e in events}

    rule_ev, done_ev = by_type["rule_issues"], by_type["done"]
    # 规则引擎产出的分数/等级/必修数，在 LLM 建议追加后一个都不能变
    assert done_ev["grade_score"] == rule_ev["grade_score"]
    assert done_ev["grade_level"] == rule_ev["grade_level"]
    assert done_ev["pass"] == rule_ev["pass"]
    assert done_ev["must_fix_count"] == rule_ev["must_fix_count"]
    # LLM 的 5 条建议只出现在 llm_issues 旁路事件里
    assert len(by_type["llm_issues"]["issues"]) == 5
    # 且全部带 source='llm' 标记（前端据此不计入"必须修复"）
    assert all(i["source"] == "llm" for i in by_type["llm_issues"]["issues"])


@pytest.mark.asyncio
async def test_prompt_sent_to_llm_uses_rubric_standard(async_db, monkeypatch):
    """发给 LLM 的提示词必须含法定评分表生成段（而非旧手写标准）。"""
    from app.schemas.ai_request import QuickQCRequest
    from app.services.ai import qc_stream_service
    from app.services.ai.llm_client import llm_client

    captured: dict = {}

    async def _capture_chat(messages, **_kwargs):
        captured["prompt"] = messages[0]["content"]
        return {"issues": [], "summary": "", "pass": True}

    monkeypatch.setattr(llm_client, "chat_json_stream", _capture_chat)

    req = QuickQCRequest(content="主诉：咳嗽2天。", record_type="outpatient")
    async for _ in qc_stream_service.run_quick_qc_stream(async_db, req):
        pass

    assert ZJ_OUTPATIENT_EMERGENCY_V2023.name in captured["prompt"]
    assert "不参与评分" in captured["prompt"]
