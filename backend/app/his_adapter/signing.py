"""HIS 对接 HMAC-SHA256 签名工具（接诊推送验签 / 病历回写签名）。

签名算法（与《MediScribe×HIS 接口规范》一致）：
    待签串 = app_id + timestamp + nonce + body_raw（请求体原文）
    sign   = hex( HMAC_SHA256(app_secret, 待签串) )
"""
import hashlib
import hmac
import time


def compute_sign(app_id: str, timestamp: str, nonce: str, body_raw: str, app_secret: str) -> str:
    """按规范拼串并算 HMAC-SHA256，返回 64 位十六进制签名。"""
    message = f"{app_id}{timestamp}{nonce}{body_raw}"
    return hmac.new(
        app_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_sign(
    app_id: str, timestamp: str, nonce: str, body_raw: str, provided_sign: str, app_secret: str
) -> bool:
    """常数时间比对签名（防时序攻击）。provided_sign 为空一律 False。"""
    expected = compute_sign(app_id, timestamp, nonce, body_raw, app_secret)
    return hmac.compare_digest(expected, provided_sign or "")


def timestamp_fresh(timestamp: str, skew_seconds: int) -> bool:
    """校验 13 位毫秒时间戳是否在允许误差内（防重放）；非法时间戳返回 False。"""
    try:
        ts = int(timestamp) / 1000.0
    except (ValueError, TypeError):
        return False
    return abs(time.time() - ts) <= skew_seconds
