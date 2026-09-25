"""质控实际发给模型的消息必须包含独立首页和当前文书边界。"""
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def capture_qc(monkeypatch):
    """隔离模型网络与审计，保留真实请求组装和规则引擎。"""
    from app.services.ai import qc_stream_service as qc
    chat = AsyncMock(return_value={"issues": []})
    monkeypatch.setattr(qc.llm_client, "chat_json_stream", chat)
    monkeypatch.setattr(qc, "get_model_options", lambda *a: {
        "temperature": 0, "max_tokens": 100, "model_name": "test"})
    for name in ("log_ai_task", "save_qc_report", "save_qc_issues"):
        monkeypatch.setattr(qc, name, AsyncMock())
    return qc, chat


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_template", [False, True])
async def test_qc_model_receives_external_patient_metadata(capture_qc, monkeypatch, async_db, legacy_template):
    """正文不含姓名性别年龄时，模型仍获得首页；旧模板缺占位符也不能漏传。"""
    from app.schemas.ai_request import QuickQCRequest
    qc, chat = capture_qc
    if legacy_template:
        monkeypatch.setattr(qc, "QC_PROMPT", "旧模板仅处理正文：{content}")
    req = QuickQCRequest(content="【主诉】头痛3天", record_type="outpatient",
                         patient_name="合成首页患者甲", patient_gender="女", patient_age="37")
    events = [event async for event in qc.run_quick_qc_stream(async_db, req)]
    prompt = "\n".join(message["content"] for message in chat.call_args.args[0])
    for value in ("合成首页患者甲", '"patient_gender": "女"', '"patient_age": "37"'):
        assert value in prompt
    assert "首页信息与正文独立存储" in prompt
    assert "不得因正文未重复首页信息而报缺失" in prompt
    assert events[-1]["grade_score"] == events[0]["grade_score"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("record_type", "boundary"), [
    ("outpatient", "不适用急诊专属条款"),
    ("emergency", "急诊专属条款适用"),
    ("first_course_record", "不得要求当前文书包含其他住院文书的专属章节"),
])
async def test_qc_model_receives_current_document_scope(capture_qc, async_db, record_type, boundary):
    """合并标准的Python适用条件不能在LLM侧丢失；急诊要求仍明确有效。"""
    from app.schemas.ai_request import QuickQCRequest
    qc, chat = capture_qc
    async for _ in qc.run_quick_qc_stream(async_db, QuickQCRequest(
            content="【主诉】头痛3天", record_type=record_type)):
        pass
    prompt = "\n".join(message["content"] for message in chat.call_args.args[0])
    assert f"当前文书类型：{record_type}" in prompt
    assert boundary in prompt


@pytest.mark.asyncio
async def test_qc_unknown_metadata_is_not_fabricated(capture_qc, async_db):
    """没传的首页值必须保持未知，不能为了防误报一概宣称首页齐全。"""
    from app.schemas.ai_request import QuickQCRequest
    qc, chat = capture_qc
    async for _ in qc.run_quick_qc_stream(async_db, QuickQCRequest(content="【主诉】头痛3天")):
        pass
    prompt = "\n".join(message["content"] for message in chat.call_args.args[0])
    assert '"patient_name": null' in prompt
    assert "未提供不等于患者档案未填写" in prompt


@pytest.mark.asyncio
async def test_supplement_receives_same_patient_and_document_context(capture_qc, monkeypatch):
    """补全已有相同入参，必须保留其元数据与适用范围，不能把误建议当真实缺项。"""
    from app.schemas.ai_request import SupplementRequest
    from app.services.ai import supplement_batch_service as svc
    qc, chat = capture_qc
    chat.return_value = {"items": []}
    monkeypatch.setattr(svc, "get_model_options", qc.get_model_options)
    monkeypatch.setattr(svc, "log_ai_task", AsyncMock())
    result = await svc.run_quick_supplement_batch(AsyncMock(), SupplementRequest(
        record_type="outpatient", patient_name="合成首页患者乙", patient_gender="男", patient_age="42",
        current_content="【主诉】头痛3天", qc_issues=[{"field_name": "患者基础信息", "suggestion": "请核对"}]))
    prompt = "\n".join(message["content"] for message in chat.call_args.args[0])
    assert "合成首页患者乙" in prompt
    assert "不适用急诊专属条款" in prompt
    assert result == {"items": []}
