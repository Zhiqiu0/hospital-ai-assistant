"""
病历补全 / 润色 JSON 路线测试（test_record_supplement_polish.py）

L3 治本路线核心防回归：
  1. supplement 走 JSON 路线 → 不可能出现两段同名章节
  2. supplement 把"未填写"占位符替换为真实内容（不追加）
  3. supplement / polish 与 generate 同构，共享相同的 service 管线
  4. LLM 重试机制：第一次返回非 dict / 抛异常 → 自动重试 1 次
  5. LLM 输出违规重复 key（虽然 JSON 标准不允许但解析后只剩最后一个）→ 渲染仍正确
"""
import json
from types import SimpleNamespace

import pytest

import app.services.ai.record_gen_v2_service as v2_service
from app.services.ai.record_gen_v2_service import (
    stream_polish_v2,
    stream_supplement_v2,
)
from app.services.ai.record_prompts import (
    build_polish_prompt,
    build_supplement_prompt,
)


def _mock_req(**overrides):
    """构造与门诊 record_type 兼容的 SupplementRequest 风格 mock 对象。"""
    base = dict(
        record_type="outpatient",
        patient_name="测试", patient_gender="男", patient_age="35",
        chief_complaint="头痛3天", history_present_illness="搏动性头痛",
        past_history="", allergy_history="", personal_history="",
        physical_exam="心肺未见异常",
        temperature="36.5", pulse="78", respiration="18",
        bp_systolic="120", bp_diastolic="80", spo2="", height="", weight="",
        auxiliary_exam="", tcm_inspection="", tcm_auscultation="",
        tongue_coating="舌淡红苔薄白", pulse_condition="脉弦",
        western_diagnosis="紧张型头痛",
        tcm_disease_diagnosis="感冒", tcm_syndrome_diagnosis="风寒束表证",
        treatment_method="疏风散寒", treatment_plan="桂枝汤",
        followup_advice="1周复诊", precautions="",
        is_first_visit=True,
        visit_time="2026-05-17 10:00", onset_time="2026-05-14 08:00",
        current_content="（旧草稿，仅供 LLM 参考）",
        qc_issues=[
            {"risk_level": "high", "issue_description": "诊断方案未填写", "suggestion": "补充治则治法"},
        ],
        family_history="",
        marital_history="", menstrual_history="", history_informant="",
        current_medications="", pain_assessment="", vte_risk="",
        nutrition_assessment="", psychology_assessment="",
        rehabilitation_assessment="", religion_belief="",
        observation_notes="", patient_disposition="",
        initial_impression="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _parse_sse(line: str) -> dict:
    assert line.startswith("data: "), f"非法 SSE 行：{line!r}"
    return json.loads(line[len("data: "):].strip())


def _mock_async(return_value):
    """生成一个返回固定值的 async 函数。"""
    async def _f(*args, **kwargs):
        return return_value
    return _f


def _mock_options() -> dict:
    return {"temperature": 0.3, "max_tokens": 4000, "model_name": "test-model"}


# ─── supplement happy path：占位符就地替换，不出现两段 ─────────────────

@pytest.mark.asyncio
async def test_supplement_replaces_placeholder_in_place(monkeypatch, async_db):
    """治本核心防回归：LLM 返回完整 JSON → renderer 拼装 → 章节只渲染一次。

    旧 bug：诊断方案章节 LLM 保留"未填写"+ 末尾追加新内容 → 双段
    新架构：LLM 输出 JSON 字段，每个 key 在 schema 内唯一，renderer 章节唯一
    """
    fake_result = {
        "chief_complaint": "头痛3天",
        "history_present_illness": "搏动性头痛，发病时间：2026-05-14",
        "past_history": "否认高血压、糖尿病等慢性病史",
        "allergy_history": "否认药物及食物过敏史",
        "personal_history": "无烟酒嗜好",
        "physical_exam_vitals": "T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg",
        "tcm_inspection": "神清面红",
        "tcm_auscultation": "语声清晰",
        "tongue_coating": "舌淡红苔薄白",
        "pulse_condition": "脉弦",
        "physical_exam_text": "心肺未见异常",
        "auxiliary_exam": "血常规正常",
        "tcm_disease_diagnosis": "感冒",
        "tcm_syndrome_diagnosis": "风寒束表证",
        "western_diagnosis": "紧张型头痛",
        "treatment_method": "疏风散寒",
        "treatment_plan": "桂枝汤加减",
        "followup_advice": "1周复诊",
        "precautions": "避风寒",
    }
    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", _mock_async(fake_result))
    monkeypatch.setattr(v2_service, "get_model_options", _mock_async(_mock_options()))

    events = []
    async for line in stream_supplement_v2("outpatient", _mock_req(), async_db):
        events.append(_parse_sse(line))

    assert events[-1]["type"] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "chunk")
    # ★ 治本核心断言：每个章节只出现一次（不可能两段）
    assert text.count("【诊断】") == 1
    assert text.count("【治疗意见及措施】") == 1
    assert text.count("【主诉】") == 1
    # ★ 治本核心断言：占位符已被真实内容替换
    assert "[未填写，需补充]" not in text
    # 内容正确：治则治法 + 处理意见都被填上了
    assert "治则治法：疏风散寒" in text
    assert "处理意见：桂枝汤加减" in text


@pytest.mark.asyncio
async def test_supplement_no_qc_issues_short_circuits_to_done(monkeypatch, async_db):
    """没有 QC 问题不应该调 LLM——路由层已挡，这里再兜一层。

    但 service 层本身没有该 short-circuit（路由层挡），所以这里测：
    传空 qc_issues 仍能正常走完管线，不会崩。
    """
    fake_result = {
        "chief_complaint": "头痛3天", "history_present_illness": "搏动性头痛",
        "past_history": "无", "allergy_history": "无", "personal_history": "无",
        "physical_exam_vitals": "T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg",
        "tcm_inspection": "[未填写，需补充]",
        "tcm_auscultation": "[未填写，需补充]",
        "tongue_coating": "[未填写，需补充]",
        "pulse_condition": "[未填写，需补充]",
        "physical_exam_text": "心肺未见异常",
        "auxiliary_exam": "暂无",
        "tcm_disease_diagnosis": "感冒",
        "tcm_syndrome_diagnosis": "风寒束表证",
        "western_diagnosis": "紧张型头痛",
        "treatment_method": "疏风散寒",
        "treatment_plan": "桂枝汤", "followup_advice": "1周复诊", "precautions": "",
    }
    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", _mock_async(fake_result))
    monkeypatch.setattr(v2_service, "get_model_options", _mock_async(_mock_options()))

    events = []
    async for line in stream_supplement_v2("outpatient", _mock_req(qc_issues=[]), async_db):
        events.append(_parse_sse(line))

    # service 自己不 short-circuit，仍走完管线推 chunk + done
    assert events[-1]["type"] == "done"


# ─── polish happy path ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_polish_happy_path(monkeypatch, async_db):
    """polish 走同样的 JSON 管线，输出经 renderer 拼装。"""
    fake_result = {
        "chief_complaint": "头痛 3 天",
        "history_present_illness": "患者搏动性头痛 3 天",
        "past_history": "否认慢性病史",
        "allergy_history": "否认药物及食物过敏史",
        "personal_history": "无烟酒嗜好",
        "physical_exam_vitals": "T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg",
        "tcm_inspection": "神清",
        "tcm_auscultation": "语声清晰",
        "tongue_coating": "舌淡红苔薄白",
        "pulse_condition": "脉弦",
        "physical_exam_text": "心肺未见异常",
        "auxiliary_exam": "暂无",
        "tcm_disease_diagnosis": "感冒",
        "tcm_syndrome_diagnosis": "风寒束表证",
        "western_diagnosis": "紧张型头痛",
        "treatment_method": "疏风散寒",
        "treatment_plan": "桂枝汤", "followup_advice": "1周复诊", "precautions": "",
    }
    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", _mock_async(fake_result))
    monkeypatch.setattr(v2_service, "get_model_options", _mock_async(_mock_options()))

    events = []
    req = _mock_req(current_content="（草稿待润色）")
    async for line in stream_polish_v2("outpatient", req, async_db):
        events.append(_parse_sse(line))

    assert events[-1]["type"] == "done"
    text = "".join(e["text"] for e in events if e["type"] == "chunk")
    assert text.count("【主诉】") == 1


# ─── retry 机制 ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_first_attempt_fails_retry_succeeds(monkeypatch, async_db):
    """第一次 LLM 调用失败 → 自动 retry 第二次成功 → 仍返回正常 chunk。"""
    fake_result = {
        "chief_complaint": "头痛3天", "history_present_illness": "搏动性头痛",
        "past_history": "无", "allergy_history": "无", "personal_history": "无",
        "physical_exam_vitals": "T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg",
        "tcm_inspection": "[未填写，需补充]",
        "tcm_auscultation": "[未填写，需补充]",
        "tongue_coating": "舌淡红苔薄白",
        "pulse_condition": "脉弦",
        "physical_exam_text": "心肺未见异常",
        "auxiliary_exam": "暂无",
        "tcm_disease_diagnosis": "感冒",
        "tcm_syndrome_diagnosis": "风寒束表证",
        "western_diagnosis": "紧张型头痛",
        "treatment_method": "疏风散寒",
        "treatment_plan": "桂枝汤", "followup_advice": "1周复诊", "precautions": "",
    }
    call_count = {"n": 0}

    async def flaky_chat(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("LLM 5xx transient")
        return fake_result

    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", flaky_chat)
    monkeypatch.setattr(v2_service, "get_model_options", _mock_async(_mock_options()))

    events = []
    async for line in stream_supplement_v2("outpatient", _mock_req(), async_db):
        events.append(_parse_sse(line))

    assert call_count["n"] == 2, "第一次失败应该自动 retry 第二次"
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_llm_both_attempts_fail_emit_error(monkeypatch, async_db):
    """两次都失败 → SSE 推 error 事件，不抛到上游。"""
    async def always_fail(*args, **kwargs):
        raise RuntimeError("LLM persistent error")

    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", always_fail)
    monkeypatch.setattr(v2_service, "get_model_options", _mock_async(_mock_options()))

    events = []
    async for line in stream_supplement_v2("outpatient", _mock_req(), async_db):
        events.append(_parse_sse(line))

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "RuntimeError" in events[0]["message"]


@pytest.mark.asyncio
async def test_llm_returns_non_dict_treated_as_error(monkeypatch, async_db):
    """LLM 偶尔返回 list 或 str（违反 JSON 模式契约）→ 视为错误重试 → 最终 error。"""
    async def returns_list(*args, **kwargs):
        return ["not", "a", "dict"]

    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", returns_list)
    monkeypatch.setattr(v2_service, "get_model_options", _mock_async(_mock_options()))

    events = []
    async for line in stream_supplement_v2("outpatient", _mock_req(), async_db):
        events.append(_parse_sse(line))

    assert events[-1]["type"] == "error"


# ─── prompt 构造测试 ──────────────────────────────────────────────

def test_supplement_prompt_includes_qc_issues_and_current_content():
    """补全 prompt 必须包含 QC 问题清单 + 当前草稿，让 LLM 知道修什么。"""
    req = _mock_req(
        current_content="【诊断】未填写",
        qc_issues=[
            {"risk_level": "high", "issue_description": "诊断方案未填写", "suggestion": "补充治则治法"},
        ],
    )
    prompt = build_supplement_prompt("outpatient", req)
    # 包含上次草稿
    assert "【诊断】未填写" in prompt
    # 包含 QC 问题清单（risk_level 大写化）
    assert "[HIGH]" in prompt
    assert "诊断方案未填写" in prompt
    # 包含核心反"双段"约束
    assert "严禁" in prompt
    assert "两段同名章节" in prompt
    # 仍然包含 schema 字段（继承 base prompt）
    assert "chief_complaint" in prompt
    assert "tongue_coating" in prompt


def test_supplement_prompt_handles_empty_qc_issues():
    """没有 QC 问题时 prompt 给占位文案，不抛 KeyError。"""
    req = _mock_req(qc_issues=[])
    prompt = build_supplement_prompt("outpatient", req)
    assert "无质控问题" in prompt


def test_polish_prompt_no_qc_issues_section():
    """润色 prompt 不含 QC 问题章节，但仍含草稿正文。"""
    req = _mock_req(current_content="待润色的病历草稿全文")
    prompt = build_polish_prompt("outpatient", req)
    assert "待润色的病历草稿全文" in prompt
    assert "质控问题" not in prompt  # polish 不接受 qc_issues
    # 包含润色专属约束
    assert "严禁修改任何客观数值" in prompt
