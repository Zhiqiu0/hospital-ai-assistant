"""语音结构化必须区分合法空提取和 AI 返回错误结构。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1 import ai_voice_structure as voice
from app.schemas.ai_request import VoiceStructureRequest


@pytest.fixture
def voice_stub(monkeypatch):
    """隔离模型与审计，保留路由的结果校验、降级和保存分支。"""
    chat = AsyncMock()
    monkeypatch.setattr(voice.llm_client, "chat_json_stream", chat)
    monkeypatch.setattr(voice, "log_action", AsyncMock())
    monkeypatch.setattr(voice, "log_ai_task", AsyncMock())
    monkeypatch.setattr(voice, "get_model_options", lambda *a: {
        "temperature": 0, "max_tokens": 100, "model_name": "test"})
    return chat


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"type": "json_object"}, {},
    {"transcript_summary": "", "speaker_dialogue": [], "inquiry": []},
    {"transcript_summary": [], "speaker_dialogue": [], "inquiry": {}},
    {"transcript_summary": "", "speaker_dialogue": {}, "inquiry": {}},
    {"transcript_summary": "", "speaker_dialogue": ["胡乱返回"], "inquiry": {}},
    {"transcript_summary": "", "speaker_dialogue": [], "inquiry": {"chief_complaint": {}}},
])
async def test_malformed_voice_result_is_degraded(payload, voice_stub):
    """业务结构不合法时明确披露失败，禁止标记成整理完成。"""
    voice_stub.return_value = payload
    result = await voice.voice_structure(
        VoiceStructureRequest(transcript="头痛三天"), AsyncMock(),
        SimpleNamespace(id="test-doc", username="测试", role="doctor"))
    assert result["degraded"] is True
    assert result["error"]
    assert result["inquiry"] == {}


@pytest.mark.asyncio
async def test_explicit_empty_voice_extraction_remains_success(voice_stub):
    """闲聊或没有新增临床事实时，显式空结构是合法结果。"""
    voice_stub.return_value = {"transcript_summary": "", "speaker_dialogue": [], "inquiry": {}}
    result = await voice.voice_structure(
        VoiceStructureRequest(transcript="谢谢，再见"), AsyncMock(),
        SimpleNamespace(id="test-doc", username="测试", role="doctor"))
    assert result["degraded"] is False
    assert result["inquiry"] == {}


@pytest.mark.asyncio
async def test_malformed_voice_keeps_existing_structured_record(voice_stub, async_db):
    """错误响应不能改写既有语音摘要、问诊字段或处理状态。"""
    from app.models.voice_record import VoiceRecord
    existing = VoiceRecord(
        id="voice-contract", doctor_id="test-doc", status="structured",
        raw_transcript="原始转写", transcript_summary="原摘要",
        structured_inquiry='{"chief_complaint":"原主诉"}', speaker_dialogue="[]")
    async_db.add(existing)
    await async_db.commit()
    voice_stub.return_value = {"type": "json_object"}
    result = await voice.voice_structure(
        VoiceStructureRequest(transcript="头痛三天", transcript_id=existing.id),
        async_db, SimpleNamespace(id="test-doc", username="测试", role="doctor"))
    assert result["degraded"] is True
    await async_db.refresh(existing)
    assert existing.transcript_summary == "原摘要"
    assert existing.structured_inquiry == '{"chief_complaint":"原主诉"}'
    assert existing.raw_transcript == "原始转写"
    assert existing.status == "structured"
