"""HIS WebSocket 通道协议层（接口规范 v1.1 第 7 章，方案 B）。

职责：消息信封模型、握手/消息签名校验、payload 原文提取、签名组装。
签名约定（与规范 7.2/7.3 一致，算法复用 signing.py 的 HMAC-SHA256）：
    握手: 待签串 = app_id + timestamp + nonce + "handshake"
    消息: 待签串 = app_id + timestamp + nonce + payload 的 JSON 序列化原文
方案 B 凭证只有一套（his_inbound_app_id/secret），双向消息均用它签名。
"""
import json
import time
import uuid
from typing import Optional

from pydantic import BaseModel, Field

from app.his_adapter.signing import compute_sign, timestamp_fresh, verify_sign

# ── 协议常数（规范 7.4 已定死，不做配置项）──
HEARTBEAT_INTERVAL = 30  # 心跳间隔（秒）：每 30s 发一次 ping
IDLE_TIMEOUT = 90        # 连续 90s 未收到任何消息 → 判定连接失效
ACK_TIMEOUT = 10         # 业务消息发出后等 ack 的超时（秒）
ACK_MAX_RESEND = 3       # ack 超时后的最大重发次数（msg_id 不变）

HANDSHAKE_LITERAL = "handshake"  # 握手签名拼串末段的固定字符串

# 消息类型（规范 7.5 对应表）
MSG_ADMIT = "encounter_admit"
MSG_WRITEBACK = "record_writeback"
MSG_REFRESH = "record_refresh"
MSG_ACK = "ack"
MSG_PING = "ping"
MSG_PONG = "pong"

# 错误码文案（与规范 2.4 一致，ack 回错时用）
ERROR_TEXT = {
    40001: "签名校验失败",
    40002: "时间戳过期或非法",
    40003: "appId 无效",
    40004: "参数缺失或格式错误",
}


class WsEnvelope(BaseModel):
    """WebSocket 消息信封（规范 7.3）。payload 为业务数据，字段同第 3 章接口。"""

    type: str
    msg_id: str
    app_id: str = ""
    timestamp: str = ""
    nonce: str = ""
    sign: str = ""
    payload: dict = Field(default_factory=dict)


def verify_handshake(
    app_id: str, timestamp: str, nonce: str, sign: str,
    expected_app_id: str, secret: str, skew_seconds: int,
) -> Optional[str]:
    """校验握手 query 参数。合法返回 None，否则返回拒绝原因（仅用于日志）。"""
    if not app_id or app_id != expected_app_id:
        return "appId 无效"
    if not timestamp_fresh(timestamp, skew_seconds):
        return "时间戳过期或非法"
    if not verify_sign(app_id, timestamp, nonce, HANDSHAKE_LITERAL, sign, secret):
        return "签名校验失败"
    return None


def extract_payload_raw(raw_text: str, parsed_payload: dict) -> Optional[str]:
    """从原始消息文本中提取 payload 的序列化原文（验签必须用厂商实际发的字节）。

    JSON 序列化不唯一（字段顺序/空格因库而异），不能重新序列化后验签。
    做法：扫描原文里每个 "payload" 键出现处，用 raw_decode 取其后的完整 JSON 值，
    与已解析的 payload 相等即认定为原文；找不到返回 None（按验签失败处理）。
    """
    decoder = json.JSONDecoder()
    search_from = 0
    while True:
        idx = raw_text.find('"payload"', search_from)
        if idx < 0:
            return None
        cursor = idx + len('"payload"')
        while cursor < len(raw_text) and raw_text[cursor] in " \t\r\n":
            cursor += 1
        if cursor < len(raw_text) and raw_text[cursor] == ":":
            cursor += 1
            while cursor < len(raw_text) and raw_text[cursor] in " \t\r\n":
                cursor += 1
            try:
                value, end = decoder.raw_decode(raw_text, cursor)
                if value == parsed_payload:
                    return raw_text[cursor:end]
            except ValueError:
                pass  # 命中的是字符串里的假 "payload"，继续往后找
        search_from = idx + 1


def verify_message(
    env: WsEnvelope, payload_raw: Optional[str],
    expected_app_id: str, secret: str, skew_seconds: int,
) -> Optional[int]:
    """校验一条上行消息的信封签名。合法返回 None，否则返回错误码（2.4）。"""
    if not env.app_id or env.app_id != expected_app_id:
        return 40003
    if not timestamp_fresh(env.timestamp, skew_seconds):
        return 40002
    if payload_raw is None or not verify_sign(
        env.app_id, env.timestamp, env.nonce, payload_raw, env.sign, secret
    ):
        return 40001
    return None


def build_signed_message(
    msg_type: str, payload: dict, app_id: str, secret: str,
    msg_id: Optional[str] = None,
) -> str:
    """组装并签名一条下行消息，返回可直接发送的 JSON 文本。

    关键约束（规范 7.3）：签名与发送必须用同一份 payload 序列化字符串，
    故先序列化一次、再用字符串拼接组装外层，绝不二次序列化。
    """
    payload_raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    msg_id = msg_id or f"ms-{uuid.uuid4().hex}"
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(app_id, ts, nonce, payload_raw, secret)
    head = json.dumps(
        {"type": msg_type, "msg_id": msg_id, "app_id": app_id,
         "timestamp": ts, "nonce": nonce, "sign": sign},
        ensure_ascii=False,
    )
    return head[:-1] + ', "payload": ' + payload_raw + "}"


def build_ack(
    ack_msg_id: str, code: int, message: str, app_id: str, secret: str,
    data: Optional[dict] = None,
) -> str:
    """组装 ack 消息：payload = 2.3 统一响应结构 + ack_msg_id（规范 7.4）。"""
    payload = {
        "code": code, "message": message, "trace_id": uuid.uuid4().hex,
        "data": data or {}, "ack_msg_id": ack_msg_id,
    }
    return build_signed_message(MSG_ACK, payload, app_id, secret)
