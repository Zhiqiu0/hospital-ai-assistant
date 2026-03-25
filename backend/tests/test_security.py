"""
安全工具单元测试：密码哈希、JWT 生成与解码
"""
import pytest
from jose import jwt
from app.core.security import hash_password, verify_password, create_access_token
from app.config import settings


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def test_hash_password_is_not_plaintext():
    hashed = hash_password("mypassword")
    assert hashed != "mypassword"
    assert len(hashed) > 20


def test_verify_password_correct():
    hashed = hash_password("secret123")
    assert verify_password("secret123", hashed) is True


def test_verify_password_wrong():
    hashed = hash_password("secret123")
    assert verify_password("wrongpass", hashed) is False


def test_create_token_contains_sub():
    token = create_access_token({"sub": "user-001"})
    assert token and isinstance(token, str)
    payload = decode_token(token)
    assert payload["sub"] == "user-001"


def test_create_token_contains_jti():
    """新签发的 token 必须包含 jti（用于 logout 黑名单）"""
    token = create_access_token({"sub": "user-002"})
    payload = decode_token(token)
    assert "jti" in payload and payload["jti"]


def test_create_token_contains_exp():
    token = create_access_token({"sub": "user-003"})
    payload = decode_token(token)
    assert "exp" in payload
