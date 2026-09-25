"""AI 合法 JSON 仍须满足业务结构，失败不能覆盖医生草稿。"""
from unittest.mock import AsyncMock

import pytest

from app.services.ai import record_gen_v2_service as gen
from app.services.ai.record_schemas import SCHEMA_MAP, PLACEHOLDER
from test_record_gen_v2_service import _mock_req, _parse_sse
from test_record_gen_v2_service import _complete_record


@pytest.fixture
def ai_stub(monkeypatch):
    """替换网络与审计，保留真实重试、校验和渲染管线。"""
    chat = AsyncMock()
    monkeypatch.setattr(gen.llm_client, "chat_json_stream", chat)
    monkeypatch.setattr(gen, "get_model_options", lambda *a: {
        "temperature": 0, "max_tokens": 100, "model_name": "test"})
    monkeypatch.setattr(gen, "log_ai_task", AsyncMock())
    monkeypatch.setattr(gen.asyncio, "sleep", AsyncMock())
    return chat


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [gen.stream_record_v2, gen.stream_polish_v2])
@pytest.mark.parametrize("payload", [
    {"type": "json_object"}, {}, {"data": {"chief_complaint": "头痛"}},
    {"chief_complaint": []}, {"chief_complaint": True},
    {"chief_complaint": "头痛", "history_present_illness": {}},
    {"chief_complaint": PLACEHOLDER}, {"chief_complaint": "  "},
    {"chief_complaint": "头痛3天"},
    _complete_record({"chief_complaint": True}),
    _complete_record({"chief_complaint": "头痛", "history_present_illness": []}),
    dict.fromkeys(SCHEMA_MAP["outpatient"], PLACEHOLDER),
    dict.fromkeys(SCHEMA_MAP["outpatient"], None),
])
async def test_invalid_record_retries_then_errors_without_save(entry, payload, ai_stub, monkeypatch):
    """错误对象不得进入保存或发出完成事件；生成和润色共用同一边界。"""
    ai_stub.return_value = payload
    save = AsyncMock(return_value=None)
    monkeypatch.setattr(gen, "_log_and_save_draft", save)
    events = [_parse_sse(line) async for line in entry(
        "outpatient", _mock_req(current_content="医生原稿"), AsyncMock())]
    assert [event["type"] for event in events] == ["error"]
    assert "结构" in events[0]["message"]
    assert ai_stub.await_count == 2
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_recovers_from_wrong_object(ai_stub, monkeypatch):
    """第一次错误格式、第二次有效内容时，只有有效病历可保存。"""
    valid = dict.fromkeys(SCHEMA_MAP["outpatient"], "")
    valid["chief_complaint"] = "头痛3天"
    ai_stub.side_effect = [{"type": "json_object"}, valid]
    save = AsyncMock(return_value="2026-09-26T12:00:00")
    monkeypatch.setattr(gen, "_log_and_save_draft", save)
    events = [_parse_sse(line) async for line in gen.stream_record_v2(
        "outpatient", _mock_req(), AsyncMock())]
    assert ai_stub.await_count == 2
    assert events[-1]["type"] == "done"
    assert "头痛3天" in save.call_args.args[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("record_type", SCHEMA_MAP)
async def test_all_record_schemas_accept_text_and_empty_fields(record_type, ai_stub):
    """未录入项允许为空，避免强制编造病史；但完整结构不可缺失。"""
    fields = list(SCHEMA_MAP[record_type])
    ai_stub.return_value = dict.fromkeys(fields, "")
    ai_stub.return_value.update({fields[0]: "医生录入内容", fields[1]: None})
    events = [_parse_sse(line) async for line in gen.stream_record_v2(
        record_type, _mock_req(), AsyncMock())]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"items": None}, {"items": "wrong"}])
async def test_supplement_missing_list_is_failure(payload, ai_stub, monkeypatch):
    """缺 items 与显式空 items 含义不同，必须向客户端披露格式失败。"""
    from app.services.ai import supplement_batch_service as svc
    from test_supplement_batch import _mock_req as supplement_req
    ai_stub.return_value = payload
    monkeypatch.setattr(svc, "get_model_options", gen.get_model_options)
    monkeypatch.setattr(svc, "log_ai_task", AsyncMock())
    result = await svc.run_quick_supplement_batch(AsyncMock(), supplement_req())
    assert result["items"] == []
    assert "error" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"issues": None}, {"issues": {}}])
async def test_qc_missing_issues_discloses_degradation(payload, ai_stub, monkeypatch, async_db):
    """规则评分仍有效，但不能把缺 issues 的模型输出解释成零建议。"""
    from app.services.ai import qc_stream_service as qc
    from app.schemas.ai_request import QuickQCRequest
    ai_stub.return_value = payload
    monkeypatch.setattr(qc, "get_model_options", gen.get_model_options)
    for name in ("log_ai_task", "save_qc_report", "save_qc_issues"):
        monkeypatch.setattr(qc, name, AsyncMock())
    events = [event async for event in qc.run_quick_qc_stream(
        async_db, QuickQCRequest(content="【主诉】头痛3天", record_type="outpatient"))]
    assert events[0]["type"] == "rule_issues"
    assert "仅返回规则引擎结果" in events[-1]["summary"]
    assert all(event["type"] != "llm_issues" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [gen.stream_record_v2, gen.stream_polish_v2])
@pytest.mark.parametrize("payload", [{"type": "json_object"},
    _complete_record({"western_diagnosis": "无出处的诊断"})])
async def test_invalid_json_preserves_existing_database_draft(entry, payload, ai_stub, monkeypatch, async_db):
    """使用真实保存服务及SQLite版本表，证明无效响应没有覆盖医生旧稿。"""
    from sqlalchemy import select
    from app.models.medical_record import RecordVersion
    from app.services.medical_record_service import MedicalRecordService
    from test_medical_record_quick_save import _make_encounter
    await _make_encounter(async_db, encounter_id="contract-existing")
    await MedicalRecordService(async_db).save_ai_draft(
        encounter_id="contract-existing", record_type="outpatient",
        content="医生已核对的原稿", user_id="doc-qs-1")
    before = (await async_db.execute(select(RecordVersion))).scalars().all()
    expected = [(row.id, dict(row.content)) for row in before]
    monkeypatch.setattr(gen, "get_encounter_id", lambda: "contract-existing")
    monkeypatch.setattr(gen, "get_user_id", lambda: "doc-qs-1")
    ai_stub.return_value = dict(payload)
    events = [_parse_sse(line) async for line in entry(
        "outpatient", _mock_req(current_content="医生已核对的原稿", western_diagnosis=""), async_db)]
    assert [event["type"] for event in events] == ["error"]
    async_db.expire_all()
    after = (await async_db.execute(select(RecordVersion))).scalars().all()
    assert [(row.id, row.content) for row in after] == expected


@pytest.mark.asyncio
async def test_save_failure_preserves_generated_chunks_and_discloses_unsaved(ai_stub, monkeypatch):
    """保存失败不丢已生成文本，但完成事件必须披露未保存以便医生重试。"""
    from app.services.medical_record_service import MedicalRecordService
    ai_stub.return_value = _complete_record({"chief_complaint": "头痛3天"})
    monkeypatch.setattr(gen, "get_encounter_id", lambda: "existing")
    monkeypatch.setattr(gen, "get_user_id", lambda: "doctor")
    monkeypatch.setattr(MedicalRecordService, "save_ai_draft", AsyncMock(
        side_effect=RuntimeError("database unavailable")))
    events = [_parse_sse(line) async for line in gen.stream_record_v2(
        "outpatient", _mock_req(), AsyncMock())]
    assert "头痛3天" in "".join(event.get("text", "") for event in events)
    assert events[-1]["type"] == "done"
    assert events[-1].get("saved") is False
    assert "保存失败" in events[-1]["warning"]
    assert "saved_updated_at" not in events[-1]


@pytest.mark.asyncio
async def test_explicit_empty_supplement_items_is_success(ai_stub, monkeypatch):
    """模型明确零条可补充结果时维持合法空返回。"""
    from app.services.ai import supplement_batch_service as svc
    from test_supplement_batch import _mock_req as supplement_req
    ai_stub.return_value = {"items": []}
    monkeypatch.setattr(svc, "get_model_options", gen.get_model_options)
    monkeypatch.setattr(svc, "log_ai_task", AsyncMock())
    assert await svc.run_quick_supplement_batch(AsyncMock(), supplement_req()) == {"items": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [gen.stream_record_v2, gen.stream_polish_v2])
async def test_guarded_empty_record_never_saves(entry, ai_stub, monkeypatch):
    """唯一内容被真实性守卫剔除后，不得把整份占位稿保存或推回覆盖旧稿。"""
    ai_stub.return_value = _complete_record({"western_diagnosis": "无出处的诊断"})
    save = AsyncMock(return_value=None)
    monkeypatch.setattr(gen, "_log_and_save_draft", save)
    events = [_parse_sse(line) async for line in entry(
        "outpatient", _mock_req(western_diagnosis="", current_content=""), AsyncMock())]
    assert [event["type"] for event in events] == ["error"]
    save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("item", [None, {"error": "bad response"},
    {"field_name": 123, "value": "文本"}, {"field_name": "舌象"},
    {"field_name": "舌象", "value": {"text": "文本"}}])
async def test_supplement_invalid_item_discloses_failure(item, ai_stub, monkeypatch):
    """列表中的错误条目既不能伪装成空结果，也不能使降级出口抛异常。"""
    from app.services.ai import supplement_batch_service as svc
    from test_supplement_batch import _mock_req as supplement_req
    ai_stub.return_value = {"items": [item]}
    monkeypatch.setattr(svc, "get_model_options", gen.get_model_options)
    monkeypatch.setattr(svc, "log_ai_task", AsyncMock())
    result = await svc.run_quick_supplement_batch(AsyncMock(), supplement_req())
    assert result["items"] == []
    assert "error" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("issues", [[{}], [{"error": "bad response"}], [
    {"field_name": "舌象", "issue_description": [], "suggestion": "补充"}]])
async def test_qc_invalid_items_disclose_degradation(issues, ai_stub, monkeypatch, async_db):
    """无有效问题描述的对象不得作为质控建议写库或发送。"""
    from app.services.ai import qc_stream_service as qc
    from app.schemas.ai_request import QuickQCRequest
    ai_stub.return_value = {"issues": issues}
    monkeypatch.setattr(qc, "get_model_options", gen.get_model_options)
    for name in ("log_ai_task", "save_qc_report", "save_qc_issues"):
        monkeypatch.setattr(qc, name, AsyncMock())
    events = [event async for event in qc.run_quick_qc_stream(
        async_db, QuickQCRequest(content="【主诉】头痛3天", record_type="outpatient"))]
    assert "仅返回规则引擎结果" in events[-1]["summary"]
    assert all(event["type"] != "llm_issues" for event in events)
    qc.save_qc_issues.assert_not_awaited()
