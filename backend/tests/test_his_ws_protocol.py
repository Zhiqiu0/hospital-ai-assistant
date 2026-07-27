"""HIS WebSocket 协议层单测：payload 原文提取、握手/消息验签、签发一致性。"""
import json
import time
import uuid

from app.his_adapter import ws_protocol as wp
from app.his_adapter.signing import compute_sign

AID, SECRET = "appHIS", "secret-key"


def _envelope_text(payload: dict, *, payload_raw: str = None, app_id=AID,
                   secret=SECRET, ts=None, sign=None) -> str:
    """手工拼一条上行消息文本（模拟厂商各种序列化风格）。"""
    payload_raw = payload_raw if payload_raw is not None else json.dumps(
        payload, ensure_ascii=False)
    ts = ts or str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = sign or compute_sign(app_id, ts, nonce, payload_raw, secret)
    return ('{"type": "encounter_admit", "msg_id": "m1", "app_id": "%s", '
            '"timestamp": "%s", "nonce": "%s", "sign": "%s", "payload": %s}'
            % (app_id, ts, nonce, sign, payload_raw))


def test_extract_payload_raw_preserves_vendor_bytes():
    """提取的必须是厂商实际发送的字节：乱序字段 + 任意空格也原样拿到。"""
    raw_payload = '{ "b" : 2,\n  "a": 1 }'  # 故意乱序 + 带空格换行
    text = _envelope_text({"a": 1, "b": 2}, payload_raw=raw_payload)
    env = wp.WsEnvelope.model_validate_json(text)
    assert wp.extract_payload_raw(text, env.payload) == raw_payload


def test_extract_payload_raw_fake_key_in_string():
    """字符串值里出现 "payload" 字样不干扰真实键的定位。"""
    payload = {"note": '假的 "payload": {"x":1} 别上当', "v": 1}
    text = _envelope_text(payload)
    env = wp.WsEnvelope.model_validate_json(text)
    extracted = wp.extract_payload_raw(text, env.payload)
    assert extracted is not None and json.loads(extracted) == payload


def test_verify_message_roundtrip():
    """厂商按规范签名 → 我方验签通过；改动 payload 后验签失败。"""
    text = _envelope_text({"visit_id": "V1", "patient_name": "张三"})
    env = wp.WsEnvelope.model_validate_json(text)
    raw = wp.extract_payload_raw(text, env.payload)
    assert wp.verify_message(env, raw, AID, SECRET, 300) is None
    # 篡改 payload 原文 → 40001
    assert wp.verify_message(env, raw.replace("V1", "V2"), AID, SECRET, 300) == 40001


def test_verify_message_wrong_appid_and_stale_ts():
    text = _envelope_text({"v": 1}, app_id="bad")
    env = wp.WsEnvelope.model_validate_json(text)
    assert wp.verify_message(env, "{}", AID, SECRET, 300) == 40003
    old_ts = str(int((time.time() - 999) * 1000))
    text2 = _envelope_text({"v": 1}, ts=old_ts)
    env2 = wp.WsEnvelope.model_validate_json(text2)
    raw2 = wp.extract_payload_raw(text2, env2.payload)
    assert wp.verify_message(env2, raw2, AID, SECRET, 300) == 40002


def test_build_signed_message_self_verifiable():
    """我方组装的下行消息，用同一套函数能解析并验签通过（签的=发的）。"""
    text = wp.build_signed_message(
        wp.MSG_WRITEBACK, {"visit_id": "V1", "record": {"主诉": "头晕3天"}},
        AID, SECRET)
    env = wp.WsEnvelope.model_validate_json(text)
    raw = wp.extract_payload_raw(text, env.payload)
    assert wp.verify_message(env, raw, AID, SECRET, 300) is None
    assert env.type == wp.MSG_WRITEBACK


def test_verify_handshake():
    ts = str(int(time.time() * 1000))
    nonce = "n1"
    good = compute_sign(AID, ts, nonce, wp.HANDSHAKE_LITERAL, SECRET)
    assert wp.verify_handshake(AID, ts, nonce, good, AID, SECRET, 300) is None
    assert wp.verify_handshake(AID, ts, nonce, "bad", AID, SECRET, 300) == "签名校验失败"
    assert wp.verify_handshake("x", ts, nonce, good, AID, SECRET, 300) == "appId 无效"


def test_build_ack_contains_ack_msg_id():
    text = wp.build_ack("his-001", 0, "success", AID, SECRET, data={"visit_id": "V1"})
    env = wp.WsEnvelope.model_validate_json(text)
    assert env.type == wp.MSG_ACK
    assert env.payload["ack_msg_id"] == "his-001"
    assert env.payload["code"] == 0 and env.payload["data"]["visit_id"] == "V1"
