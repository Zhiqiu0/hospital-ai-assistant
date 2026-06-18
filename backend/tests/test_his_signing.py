"""HIS 签名工具单测。"""
import time

from app.his_adapter.signing import compute_sign, verify_sign, timestamp_fresh


def test_compute_sign_deterministic():
    """同样入参算出同样签名，且为 64 位十六进制。"""
    sig = compute_sign("appA", "1700000000000", "n1", '{"a":1}', "secret")
    assert sig == compute_sign("appA", "1700000000000", "n1", '{"a":1}', "secret")
    assert len(sig) == 64 and all(c in "0123456789abcdef" for c in sig)


def test_verify_sign_pass_and_fail():
    """正确签名通过，篡改任一项失败。"""
    args = ("appA", "1700000000000", "n1", '{"a":1}', "secret")
    sig = compute_sign(*args)
    assert verify_sign("appA", "1700000000000", "n1", '{"a":1}', sig, "secret") is True
    # 篡改 body
    assert verify_sign("appA", "1700000000000", "n1", '{"a":2}', sig, "secret") is False
    # 错密钥
    assert verify_sign("appA", "1700000000000", "n1", '{"a":1}', sig, "wrong") is False


def test_timestamp_fresh():
    """当前时间戳通过，超出误差或非法失败。"""
    now_ms = str(int(time.time() * 1000))
    assert timestamp_fresh(now_ms, 300) is True
    old_ms = str(int((time.time() - 600) * 1000))
    assert timestamp_fresh(old_ms, 300) is False
    assert timestamp_fresh("not-a-number", 300) is False
