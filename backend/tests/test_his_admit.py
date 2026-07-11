"""接诊推送接收接口单测。"""
import json
import time
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.his_adapter.signing import compute_sign
from app.main import app


@pytest_asyncio.fixture
async def his_client(monkeypatch):
    """开启保险丝 + 注入测试验签凭证。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    monkeypatch.setattr(settings, "his_inbound_app_id", "appHIS")
    monkeypatch.setattr(settings, "his_inbound_app_secret", "secret-key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _headers(body_raw: str, app_id="appHIS", secret="secret-key", ts=None, nonce=None):
    ts = ts or str(int(time.time() * 1000))
    # 默认每次用唯一 nonce：本地若有真实 Redis，防重放会记住 nonce（TTL 数分钟），
    # 固定 nonce 会让跨用例/跨轮次的请求被误判为重放。需要复现重放的用例显式传同一个。
    nonce = nonce or f"n-{uuid.uuid4().hex}"
    sign = compute_sign(app_id, ts, nonce, body_raw, secret)
    return {"X-App-Id": app_id, "X-Timestamp": ts, "X-Nonce": nonce,
            "X-Sign": sign, "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_admit_valid(his_client):
    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    res = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=_headers(body))
    assert res.status_code == 200
    j = res.json()
    assert j["code"] == 0 and j["data"]["visit_id"] == "V1"


@pytest.mark.asyncio
async def test_admit_bad_sign(his_client):
    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    headers = _headers(body)
    headers["X-Sign"] = "deadbeef"
    res = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=headers)
    assert res.json()["code"] == 40001


@pytest.mark.asyncio
async def test_admit_stale_timestamp(his_client):
    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    old_ts = str(int((time.time() - 1000) * 1000))
    res = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=_headers(body, ts=old_ts))
    assert res.json()["code"] == 40002


@pytest.mark.asyncio
async def test_admit_wrong_appid(his_client):
    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    res = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=_headers(body, app_id="bad"))
    assert res.json()["code"] == 40003


@pytest.mark.asyncio
async def test_admit_replay_rejected(his_client, monkeypatch):
    """签名合法但 nonce 已用过（重放）→ 40006 拒绝。

    用桩模拟 Redis 有效时的行为：首次 claim 返回 True，同 nonce 再 claim 返回 False。
    """
    from app.services import redis_cache as rc_module

    seen: set = set()

    async def fake_claim_nonce(scope, nonce, *, ttl):
        key = (scope, nonce)
        if key in seen:
            return False
        seen.add(key)
        return True

    monkeypatch.setattr(rc_module.redis_cache, "claim_nonce", fake_claim_nonce)

    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    headers = _headers(body, nonce="replay-fixed")  # 两次请求刻意用同一个 nonce
    first = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=headers)
    assert first.json()["code"] == 0
    replay = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=headers)
    assert replay.json()["code"] == 40006
