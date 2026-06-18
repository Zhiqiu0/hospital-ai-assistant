"""接诊推送接收接口单测。"""
import json
import time

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


def _headers(body_raw: str, app_id="appHIS", secret="secret-key", ts=None):
    ts = ts or str(int(time.time() * 1000))
    nonce = "n-123"
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
