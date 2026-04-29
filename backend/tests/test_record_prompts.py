"""
病历 JSON 生成 prompt 构造器测试（test_record_prompts.py）

防回归点：
  1. prompt 包含 schema 全部字段说明（LLM 才知道要填哪些 key）
  2. prompt 包含真实性硬约束（防 LLM 编造）
  3. 医生录入数据正确注入
  4. 急诊不含中医字段说明（与急诊不需要中医四诊一致）
  5. record_type 路由分发正确
"""
from types import SimpleNamespace

import pytest

from app.services.ai.record_prompts import (
    NEW_ARCH_RECORD_TYPES,
    build_emergency_prompt,
    build_outpatient_prompt,
    build_record_prompt,
)
from app.services.ai.record_schemas import EMERGENCY_SCHEMA, OUTPATIENT_SCHEMA


def _mock_outpatient_req(**overrides):
    """构造门诊 quick-generate 请求 mock；用 SimpleNamespace 模拟 Pydantic 对象。"""
    base = dict(
        patient_name="测试", patient_gender="男", patient_age="35",
        chief_complaint="头痛3天", history_present_illness="搏动性头痛",
        past_history="高血压", allergy_history="无", personal_history="无烟酒",
        physical_exam="心肺听诊未见异常",
        temperature="36.5", pulse="78", respiration="18",
        bp_systolic="120", bp_diastolic="80", spo2="", height="", weight="",
        auxiliary_exam="血常规正常",
        tcm_inspection="神清面红", tcm_auscultation="语声清晰",
        tongue_coating="舌淡红苔薄白", pulse_condition="脉弦",
        western_diagnosis="紧张型头痛",
        tcm_disease_diagnosis="感冒", tcm_syndrome_diagnosis="风寒束表证",
        treatment_method="疏风散寒", treatment_plan="桂枝汤",
        followup_advice="1周复诊", precautions="避风寒",
        is_first_visit=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _mock_emergency_req(**overrides):
    base = dict(
        patient_name="测试", patient_gender="男", patient_age="60",
        chief_complaint="胸痛 2 小时", history_present_illness="突发胸痛",
        past_history="高血压", allergy_history="无", personal_history="",
        physical_exam="心率 100，律齐",
        temperature="36.8", pulse="100", respiration="22",
        bp_systolic="90", bp_diastolic="60", spo2="", height="", weight="",
        auxiliary_exam="心电图 ST 段抬高",
        initial_impression="急性心肌梗死",
        treatment_plan="硝酸甘油舌下含服",
        observation_notes="",
        patient_disposition="收入住院",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ─── 白名单 ──────────────────────────────────────────────────────────


class TestWhitelist:
    def test_outpatient_and_emergency_in_whitelist(self):
        assert "outpatient" in NEW_ARCH_RECORD_TYPES
        assert "emergency" in NEW_ARCH_RECORD_TYPES

    def test_admission_and_inpatient_in_whitelist(self):
        """L3 阶段 3 已全量接入：住院 + 7 个病程类全部在白名单。"""
        for rt in [
            "admission_note", "first_course_record", "course_record",
            "senior_round", "discharge_record",
            "pre_op_summary", "op_record", "post_op_record",
        ]:
            assert rt in NEW_ARCH_RECORD_TYPES, f"{rt} 未注册到白名单"

    def test_unknown_record_type_not_in_whitelist(self):
        """随机字符串绝不在白名单（确保白名单是显式注册而非通配）。"""
        assert "unknown_xxx" not in NEW_ARCH_RECORD_TYPES


# ─── 门诊 prompt ─────────────────────────────────────────────────────


class TestOutpatientPrompt:
    def test_contains_all_schema_keys(self):
        """prompt 必须列出 OUTPATIENT_SCHEMA 全部字段，否则 LLM 不知道要填哪些 key。"""
        prompt = build_outpatient_prompt(_mock_outpatient_req())
        for key in OUTPATIENT_SCHEMA:
            assert f"- {key}:" in prompt, f"prompt 缺字段说明 {key!r}"

    def test_contains_truthfulness_rules(self):
        """必须含核心约束（防 LLM 编造）。"""
        prompt = build_outpatient_prompt(_mock_outpatient_req())
        assert "禁止编造" in prompt
        assert "[未填写，需补充]" in prompt
        assert "T:36.5℃ P:78次/分" in prompt  # 生命体征行格式示例

    def test_injects_doctor_inputs(self):
        """医生录入的关键字段都要注入进 prompt。"""
        prompt = build_outpatient_prompt(_mock_outpatient_req())
        assert "头痛3天" in prompt           # chief_complaint
        assert "舌淡红苔薄白" in prompt       # tongue_coating
        assert "感冒" in prompt               # tcm_disease_diagnosis
        assert "桂枝汤" in prompt             # treatment_plan

    def test_revisit_label(self):
        """复诊请求 → prompt 第一句应含'复诊'。"""
        prompt = build_outpatient_prompt(_mock_outpatient_req(is_first_visit=False))
        assert "复诊病历" in prompt

    def test_first_visit_label(self):
        """初诊请求 → 含'初诊'。"""
        prompt = build_outpatient_prompt(_mock_outpatient_req(is_first_visit=True))
        assert "初诊病历" in prompt

    def test_empty_field_uses_placeholder_in_request_block(self):
        """医生未录入字段 → 注入到 prompt 的'医生录入'段落用 [未填写，需补充] 占位。"""
        prompt = build_outpatient_prompt(_mock_outpatient_req(tongue_coating=""))
        # request_block 含"舌象：[未填写，需补充]"
        assert "舌象：[未填写，需补充]" in prompt


# ─── 急诊 prompt ─────────────────────────────────────────────────────


class TestEmergencyPrompt:
    def test_contains_emergency_schema_keys(self):
        prompt = build_emergency_prompt(_mock_emergency_req())
        for key in EMERGENCY_SCHEMA:
            assert f"- {key}:" in prompt, f"急诊 prompt 缺字段 {key!r}"

    def test_no_tcm_keys_in_emergency_schema(self):
        """急诊 schema 字段表里不应有中医字段（约束段落里作为反例提及不算）。"""
        prompt = build_emergency_prompt(_mock_emergency_req())
        # 检查 schema 列表（"- key:" 模式）不含中医字段
        assert "- tcm_inspection:" not in prompt
        assert "- tongue_coating:" not in prompt
        assert "- pulse_condition:" not in prompt

    def test_disposition_constraint(self):
        """急诊 prompt 必须给 LLM 明确的患者去向五选一。"""
        prompt = build_emergency_prompt(_mock_emergency_req())
        for option in ["回家观察", "留院观察", "收入住院", "转院", "手术室"]:
            assert option in prompt

    def test_injects_emergency_inputs(self):
        prompt = build_emergency_prompt(_mock_emergency_req())
        assert "胸痛 2 小时" in prompt
        assert "急性心肌梗死" in prompt
        assert "收入住院" in prompt


# ─── 路由 ────────────────────────────────────────────────────────────


class TestBuildRecordPrompt:
    def test_routes_outpatient(self):
        prompt = build_record_prompt("outpatient", _mock_outpatient_req())
        assert "中医" in prompt and "舌象" in prompt

    def test_routes_emergency(self):
        prompt = build_record_prompt("emergency", _mock_emergency_req())
        assert "急诊" in prompt and "患者去向" in prompt

    def test_unknown_record_type_raises(self):
        """白名单外的 record_type 调进来应抛 ValueError（让路由层尽快发现 bug）。"""
        with pytest.raises(ValueError):
            build_record_prompt("unknown_xxx", _mock_outpatient_req())
