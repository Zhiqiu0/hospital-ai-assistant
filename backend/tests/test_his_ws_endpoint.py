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

    # 业务落地（建档/派医生）由 test_his_admit_service.py 专测；这里打桩隔离 DB
    from app.his_adapter import admit_service

    async def fake_handle_admit(payload):
        return admit_service.AdmitResult(
            encounter_id="enc-test", patient_id="p-test",
            patient_name=payload.patient_name, doctor_id="d-test", reused=False,
        )

    monkeypatch.setattr(admit_service, "handle_admit", fake_handle_admit)
    return TestClient(app)


def _handshake_url(app_id=AID, secret=SECRET, sign=None, nonce=None) -> str:
    ts = str(int(time.time() * 1000))
    nonce = nonce or uuid.uuid4().hex
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


def _recv_skip_heartbeat(ws) -> wp.WsEnvelope:
    """读一条非心跳消息：CI 跑器卡顿超过 30s 时，服务端心跳 ping 可能插到
    业务应答之前，直接读一条会偶发拿到 ping 帧（CI 偶发红）。跳过即可。"""
    while True:
        env = wp.WsEnvelope.model_validate_json(ws.receive_text())
        if env.type != wp.MSG_PING:
            return env


def test_ws_admit_roundtrip(ws_env):
    """握手成功 → 发接诊推送 → 收到 code=0 的 ack（回声 visit_id）。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(visit_id="V123"))
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_ACK
        assert env.payload["code"] == 0
        assert env.payload["data"]["visit_id"] == "V123"


def test_ws_handshake_bad_sign_rejected(ws_env):
    """握手签名错误 → 连接被拒绝（无法建立会话）。"""
    with pytest.raises(Exception):
        with ws_env.websocket_connect(_handshake_url(sign="deadbeef")):
            pass


def test_ws_handshake_replay_rejected(ws_env):
    """同一握手 nonce 重放（相同 URL 再建连）→ 被防重放拦截（2026-08-11 审计延期项）。

    ws_env 的 fake_claim_nonce 用 seen 集模拟 Redis：首次 claim True、重放 False。
    """
    ts = str(int(time.time() * 1000))
    fixed_nonce = "handshake-replay-fixed"
    sign = compute_sign(AID, ts, fixed_nonce, wp.HANDSHAKE_LITERAL, SECRET)
    url = (f"/api/v1/his/ws?app_id={AID}&timestamp={ts}"
           f"&nonce={fixed_nonce}&sign={sign}")
    # 首次建连成功
    with ws_env.websocket_connect(url):
        pass
    # 同 nonce 重放 → 拒绝
    with pytest.raises(Exception):
        with ws_env.websocket_connect(url):
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
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_ACK and env.payload["code"] == 40001


def test_ws_ping_gets_pong(ws_env):
    """厂商 ping → 我方回 pong（心跳免验签）。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(json.dumps({"type": "ping", "msg_id": "p1"}))
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_PONG


def test_ws_duplicate_msg_id_idempotent(ws_env):
    """同 msg_id 重发（模拟厂商 ack 丢失后重试）→ 幂等地再回成功 ack。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        fixed = "his-dup-001"
        ws.send_text(_admit_text(visit_id="V9", msg_id=fixed))
        first = _recv_skip_heartbeat(ws)
        assert first.payload["code"] == 0
        ws.send_text(_admit_text(visit_id="V9", msg_id=fixed))
        second = _recv_skip_heartbeat(ws)
        assert second.payload["code"] == 0  # 不报错、不重复处理
        assert second.payload["ack_msg_id"] == fixed


def test_ws_admit_business_error_gets_40007(ws_env, monkeypatch):
    """业务拒收（医生工号未注册）→ ack code=40007，message 带具体原因。"""
    from app.his_adapter import admit_service

    async def rejecting_handle_admit(payload):
        raise admit_service.AdmitError(40007, "医生工号 D404 未在 MediScribe 注册或已停用")

    monkeypatch.setattr(admit_service, "handle_admit", rejecting_handle_admit)
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(visit_id="V404"))
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_ACK
        assert env.payload["code"] == 40007
        assert "D404" in env.payload["message"]


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
        env = _recv_skip_heartbeat(ws)
        assert env.payload["code"] == 40004


def test_probe_handshake_not_logged_as_warning(ws_env, caplog):
    """无凭证探测（健康监控/端口扫描）不得写 WARNING 到 error.log。

    uptime-kuma 对 /api/v1/his/ws 的存活探测每 60 秒一次、不带任何凭证。
    若按 WARNING 记，一天 1440 条会把「error.log 只装 WARNING 以上」这个
    排障入口彻底淹掉。带了凭证但不对的仍须保持 WARNING（真实鉴权失败）。
    """
    import logging
    with caplog.at_level(logging.WARNING, logger="app.api.v1.his_ws"):
        with pytest.raises(Exception):
            with ws_env.websocket_connect("/api/v1/his/ws"):  # 一个参数都不带
                pass
    assert not [r for r in caplog.records if "handshake_rejected" in r.message], \
        "无凭证探测不应产生 WARNING"

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.api.v1.his_ws"):
        with pytest.raises(Exception):
            with ws_env.websocket_connect(_handshake_url(sign="deadbeef")):
                pass
    assert [r for r in caplog.records if "handshake_rejected" in r.message], \
        "带凭证但签名错属真实鉴权失败，必须保留 WARNING"
