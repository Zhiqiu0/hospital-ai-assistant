"""
病历 JSON 生成 service 测试（test_record_gen_v2_service.py）

防回归点：
  1. happy path：LLM 返回 dict → SSE 推 chunk + done，chunk 含完整渲染文本
  2. LLM 异常 → SSE 推 error 事件，不抛到上游
  3. 未支持的 record_type → SSE 推 error 事件
  4. SSE 事件格式跟前端协议对齐（type=chunk/done/error）
"""
import json
from types import SimpleNamespace

import pytest

import app.services.ai.record_gen_v2_service as v2_service
from app.services.ai.record_gen_v2_service import stream_record_v2


def _mock_req(**overrides):
    base = dict(
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
        visit_time="2026-04-29 10:00", onset_time="2026-04-26 08:00",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _parse_sse(line: str) -> dict:
    """把 'data: {...}\\n\\n' 解析回 dict，方便断言。"""
    assert line.startswith("data: "), f"非法 SSE 行：{line!r}"
    payload = line[len("data: "):].strip()
    return json.loads(payload)


# ─── happy path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outpatient_happy_path(monkeypatch, async_db):
    """LLM 返回完整 dict → SSE 推 chunk(完整文本) + done。"""
    fake_result = {
        "chief_complaint": "头痛3天",
        "history_present_illness": "搏动性头痛",
        "past_history": "高血压",
        "allergy_history": "否认",
        "personal_history": "无烟酒",
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

    async def fake_chat_json_stream(*args, **kwargs):
        return fake_result

    async def fake_get_model_options(*args, **kwargs):
        return {"temperature": 0.3, "max_tokens": 4000, "model_name": "test-model"}

    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", fake_chat_json_stream)
    monkeypatch.setattr(v2_service, "get_model_options", fake_get_model_options)

    events = []
    async for line in stream_record_v2("outpatient", _mock_req(), async_db):
        events.append(_parse_sse(line))

    # 应该恰好两个事件：chunk + done
    assert len(events) == 2
    assert events[0]["type"] == "chunk"
    assert events[1]["type"] == "done"
    # chunk 文本含完整章节结构（行格式契约）
    text = events[0]["text"]
    assert "【主诉】" in text
    assert "切诊·舌象：舌淡红苔薄白" in text
    assert "中医诊断：感冒 — 风寒束表证" in text
    # 元数据首行（visit_time / onset_time 注入）
    assert text.startswith("就诊时间：2026-04-29 10:00")


# ─── error paths ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_exception_emits_error_event(monkeypatch, async_db):
    """LLM 抛异常 → SSE 推 error 事件，不抛到上游（路由层不会 500）。"""
    async def fake_chat_json_stream(*args, **kwargs):
        raise RuntimeError("LLM timeout")

    async def fake_get_model_options(*args, **kwargs):
        return {"temperature": 0.3, "max_tokens": 4000, "model_name": "test-model"}

    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", fake_chat_json_stream)
    monkeypatch.setattr(v2_service, "get_model_options", fake_get_model_options)

    events = []
    async for line in stream_record_v2("outpatient", _mock_req(), async_db):
        events.append(_parse_sse(line))

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "RuntimeError" in events[0]["message"]


@pytest.mark.asyncio
async def test_unsupported_record_type_emits_error(monkeypatch, async_db):
    """白名单外的 record_type → SSE 推 error 事件，不会进 LLM 调用。

    防御层：路由层应已过滤，但 service 内部再兜一层免得未来路由 bug 直接 500。
    """
    # 不需要 mock chat_json_stream，因为不应该被调用
    events = []
    async for line in stream_record_v2("unknown_xxx", _mock_req(), async_db):
        events.append(_parse_sse(line))

    assert len(events) == 1
    assert events[0]["type"] == "error"


@pytest.mark.asyncio
async def test_render_failure_emits_error(monkeypatch, async_db):
    """LLM 返回的 dict 渲染失败（理论上不会发生，但兜底要测）。"""
    # 让 render_record 抛异常
    def fake_render(*args, **kwargs):
        raise ValueError("render bug")

    async def fake_chat_json_stream(*args, **kwargs):
        return {"chief_complaint": "x"}

    async def fake_get_model_options(*args, **kwargs):
        return {"temperature": 0.3, "max_tokens": 4000, "model_name": "test-model"}

    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", fake_chat_json_stream)
    monkeypatch.setattr(v2_service, "get_model_options", fake_get_model_options)
    monkeypatch.setattr(v2_service, "render_record", fake_render)

    events = []
    async for line in stream_record_v2("outpatient", _mock_req(), async_db):
        events.append(_parse_sse(line))

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "ValueError" in events[0]["message"]


# ─── 急诊 happy path ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emergency_happy_path(monkeypatch, async_db):
    """急诊场景：mock 返回完整 dict → 渲染含【急诊处置】【患者去向】等急诊章节。"""
    fake_result = {
        "chief_complaint": "胸痛 2 小时",
        "history_present_illness": "突发胸痛",
        "past_history": "高血压",
        "allergy_history": "否认",
        "physical_exam_vitals": "T:36.8℃ P:100次/分 R:22次/分 BP:90/60mmHg",
        "physical_exam_text": "心率 100，律齐",
        "auxiliary_exam": "心电图 ST 段抬高",
        "diagnosis": "急性心肌梗死",
        "treatment_plan": "硝酸甘油舌下含服",
        "observation_notes": "",
        "patient_disposition": "收入住院",
    }

    async def fake_chat_json_stream(*args, **kwargs):
        return fake_result

    async def fake_get_model_options(*args, **kwargs):
        return {"temperature": 0.3, "max_tokens": 4000, "model_name": "test-model"}

    monkeypatch.setattr(v2_service.llm_client, "chat_json_stream", fake_chat_json_stream)
    monkeypatch.setattr(v2_service, "get_model_options", fake_get_model_options)

    req = _mock_req(initial_impression="急性心肌梗死", patient_disposition="收入住院")
    events = []
    async for line in stream_record_v2("emergency", req, async_db):
        events.append(_parse_sse(line))

    assert events[-1]["type"] == "done"
    text = events[0]["text"]
    assert "【急诊处置】" in text
    assert "【患者去向】" in text
    # 急诊不含中医四诊子行
    assert "切诊·舌象：" not in text
