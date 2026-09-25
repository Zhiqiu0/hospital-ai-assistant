"""无法提取原始载荷时仍回签名错误，不能因日志异常中断消息循环。"""
import json
import time
from unittest.mock import AsyncMock

import pytest

from app.api.v1.his_ws import _handle_message
from app.config import settings
from app.his_adapter import ws_protocol as wp
from app.his_adapter.signing import compute_sign


@pytest.mark.asyncio
@pytest.mark.parametrize("payload_kind", ["missing", "escaped"])
async def test_unextractable_payload_returns_signed_ack_and_keeps_processing(monkeypatch, payload_kind):
    """合法凭证也不能让缺失或转义键载荷绕过原文验签；后续心跳仍可处理。"""
    monkeypatch.setattr(settings, "his_inbound_app_id", "test-app")
    monkeypatch.setattr(settings, "his_inbound_app_secret", "test-secret")
    raw = wp.build_signed_message(wp.MSG_ADMIT, {}, "test-app", "test-secret")
    message = json.loads(raw)
    if payload_kind == "missing":
        message.pop("payload")
        raw = json.dumps(message)
    else:
        raw = raw.replace('"payload"', '"pay\\u006coad"')
    socket = AsyncMock()
    await _handle_message(socket, raw)
    ack_raw = socket.send_text.call_args.args[0]
    ack = wp.WsEnvelope.model_validate_json(ack_raw)
    assert ack.type == wp.MSG_ACK
    assert ack.payload["code"] == 40001
    assert ack.payload["ack_msg_id"] == message["msg_id"]
    assert wp.verify_message(ack, wp.extract_payload_raw(ack_raw, ack.payload), "test-app", "test-secret", 300) is None
    await _handle_message(socket, '{"type":"ping"}')
    assert json.loads(socket.send_text.call_args.args[0])["type"] == wp.MSG_PONG


@pytest.mark.asyncio
@pytest.mark.parametrize("payload_raw", ['{ "text" : "中文" }', '{"text":"\\u4e2d\\u6587"}'])
async def test_original_signed_bytes_are_still_used(monkeypatch, payload_raw):
    """空白和Unicode转义不同的原文均可验签；重新序列化的签名必须被拒绝。"""
    monkeypatch.setattr(settings, "his_inbound_app_id", "test-app")
    monkeypatch.setattr(settings, "his_inbound_app_secret", "test-secret")
    timestamp = str(int(time.time() * 1000))
    envelope = {"type": "test_business", "msg_id": "raw-bytes", "app_id": "test-app",
                "timestamp": timestamp, "nonce": "raw-nonce"}
    socket = AsyncMock()
    for signing_payload, expected_code in [(payload_raw, 40004), ('{"text":"中文"}', 40001)]:
        envelope["sign"] = compute_sign("test-app", timestamp, "raw-nonce", signing_payload, "test-secret")
        raw = json.dumps(envelope)[:-1] + ',"payload":' + payload_raw + '}'
        await _handle_message(socket, raw)
        ack = json.loads(socket.send_text.call_args.args[0])["payload"]
        assert ack["code"] == expected_code
        if expected_code == 40004:
            # 已通过鉴权并抵达业务类型检查，而非信封解析或验签分支拒绝。
            assert ack["message"] == "未知消息类型"
