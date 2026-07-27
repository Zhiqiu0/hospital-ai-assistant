"""HIS WebSocket 路由端到端测试（TestClient 走真实握手 + 消息循环）。"""
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.his_adapter import ws_protocol as wp
from app.his_adapter.signing import compute_sign
from app.main import app

AID, SECRET = "appHIS", "secret-key"


@pytest.fixture
def ws_env(monkeypatch):
    """开保险丝 + 注入测试凭证 + 消息去重打桩（不依赖真实 Redis）。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    monkeypatch.setattr(settings, "his_inbound_app_id", AID)
    monkeypatch.setattr(settings, "his_inbound_app_secret", SECRET)

    from app.services import redis_cache as rc_module
    seen: set = set()

    async def fake_claim_nonce(scope, nonce, *, ttl):
        key = (scope, nonce)
        if key in seen:
            return False
        seen.add(key)
        return True

    monkeypatch.setattr(rc_module.redis_cache, "claim_nonce", fake_claim_nonce)
    return TestClient(app)


def _handshake_url(app_id=AID, secret=SECRET, sign=None) -> str:
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = sign or compute_sign(app_id, ts, nonce, wp.HANDSHAKE_LITERAL, secret)
    return (f"/api/v1/his/ws?app_id={app_id}&timestamp={ts}"
            f"&nonce={nonce}&sign={sign}")


def _admit_text(visit_id="V1", msg_id=None, secret=SECRET) -> str:
    payload_raw = json.dumps(
        {"visit_id": visit_id, "hospital_code": "H1", "patient_name": "张三"},
        ensure_ascii=False)
    msg_id = msg_id or f"his-{uuid.uuid4().hex}"
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(AID, ts, nonce, payload_raw, secret)
    return ('{"type": "encounter_admit", "msg_id": "%s", "app_id": "%s", '
            '"timestamp": "%s", "nonce": "%s", "sign": "%s", "payload": %s}'
            % (msg_id, AID, ts, nonce, sign, payload_raw))


def test_ws_admit_roundtrip(ws_env):
    """握手成功 → 发接诊推送 → 收到 code=0 的 ack（回声 visit_id）。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(visit_id="V123"))
        env = wp.WsEnvelope.model_validate_json(ws.receive_text())
        assert env.type == wp.MSG_ACK
        assert env.payload["code"] == 0
        assert env.payload["data"]["visit_id"] == "V123"


def test_ws_handshake_bad_sign_rejected(ws_env):
    """握手签名错误 → 连接被拒绝（无法建立会话）。"""
    with pytest.raises(Exception):
        with ws_env.websocket_connect(_handshake_url(sign="deadbeef")):
            pass


def test_ws_disabled_rejected(ws_env, monkeypatch):
    """保险丝关闭 → 拒绝握手。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", False)
    with pytest.raises(Exception):
        with ws_env.websocket_connect(_handshake_url()):
            pass


def test_ws_bad_message_sign_gets_40001(ws_env):
    """消息签名错误（用错密钥）→ ack code=40001。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(secret="wrong-secret"))
        env = wp.WsEnvelope.model_validate_json(ws.receive_text())
        assert env.type == wp.MSG_ACK and env.payload["code"] == 40001


def test_ws_ping_gets_pong(ws_env):
    """厂商 ping → 我方回 pong（心跳免验签）。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(json.dumps({"type": "ping", "msg_id": "p1"}))
        env = wp.WsEnvelope.model_validate_json(ws.receive_text())
        assert env.type == wp.MSG_PONG


def test_ws_duplicate_msg_id_idempotent(ws_env):
    """同 msg_id 重发（模拟厂商 ack 丢失后重试）→ 幂等地再回成功 ack。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        fixed = "his-dup-001"
        ws.send_text(_admit_text(visit_id="V9", msg_id=fixed))
        first = wp.WsEnvelope.model_validate_json(ws.receive_text())
        assert first.payload["code"] == 0
        ws.send_text(_admit_text(visit_id="V9", msg_id=fixed))
        second = wp.WsEnvelope.model_validate_json(ws.receive_text())
        assert second.payload["code"] == 0  # 不报错、不重复处理
        assert second.payload["ack_msg_id"] == fixed


def test_ws_unknown_type_gets_40004(ws_env):
    """未知消息类型 → ack code=40004。"""
    payload_raw = "{}"
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(AID, ts, nonce, payload_raw, SECRET)
    text = ('{"type": "mystery", "msg_id": "m9", "app_id": "%s", '
            '"timestamp": "%s", "nonce": "%s", "sign": "%s", "payload": %s}'
            % (AID, ts, nonce, sign, payload_raw))
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(text)
        env = wp.WsEnvelope.model_validate_json(ws.receive_text())
        assert env.payload["code"] == 40004
