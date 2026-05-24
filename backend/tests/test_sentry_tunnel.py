"""Sentry tunnel endpoint 测试（tests/test_sentry_tunnel.py）

核心契约：
  1. 后端没配 SENTRY_DSN → 直接返 {"status": "no-dsn"}，不调上游
  2. body 超过 100KB → 413
  3. envelope header 里的 dsn host 跟 settings.sentry_dsn host 不一致 → 400（防 SSRF）
  4. 上游成功 → {"status": "ok", "upstream_status": 200}
  5. 上游挂了/超时 → {"status": "upstream-failed"}，不抛 5xx（fire-and-forget）
  6. DSN 解析 helper 的边界用例（空 / 缺 host / 缺 project_id）
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.api.v1 import sentry_tunnel as st
from app.main import app


def _envelope(dsn: str) -> bytes:
    """构造一个最小可解析的 Sentry envelope（header 一行 + payload 一行）。"""
    header = json.dumps({"dsn": dsn, "event_id": "abcd1234"}).encode()
    payload = b'{"type":"event"}\n{"message":"test"}'
    return header + b"\n" + payload


# ── 单元测试：DSN 解析 helper ─────────────────────────────────────────────


def test_parse_dsn_normal():
    h, p = st._parse_dsn_host_and_project("https://abc@o123.ingest.us.sentry.io/4567")
    assert h == "o123.ingest.us.sentry.io"
    assert p == "4567"


def test_parse_dsn_empty_returns_none():
    assert st._parse_dsn_host_and_project("") is None
    assert st._parse_dsn_host_and_project("not-a-url") is None


def test_parse_dsn_no_project_id():
    # path 为空 / 仅 /
    assert st._parse_dsn_host_and_project("https://abc@host.com/") is None


# ── 集成测试：tunnel endpoint 行为 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_tunnel_returns_no_dsn_when_backend_not_configured(monkeypatch):
    """后端没配 SENTRY_DSN → 直接 200 静默，不调上游。"""
    monkeypatch.setattr(st.settings, "sentry_dsn", "")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as cli:
        r = await cli.post("/api/v1/sentry-tunnel", content=b"any payload")
    assert r.status_code == 200
    assert r.json() == {"status": "no-dsn"}


@pytest.mark.asyncio
async def test_tunnel_payload_too_large(monkeypatch):
    """body > 100KB → 413。"""
    monkeypatch.setattr(st.settings, "sentry_dsn", "https://k@o1.ingest.us.sentry.io/2")
    transport = ASGITransport(app=app)
    huge = b"x" * (st.MAX_BODY_BYTES + 1)
    async with AsyncClient(transport=transport, base_url="http://test") as cli:
        r = await cli.post("/api/v1/sentry-tunnel", content=huge)
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_tunnel_rejects_dsn_host_mismatch(monkeypatch):
    """envelope dsn host 跟 settings.sentry_dsn host 不一致 → 400（防 SSRF）。"""
    monkeypatch.setattr(st.settings, "sentry_dsn", "https://k@o1.ingest.us.sentry.io/2")
    # 构造一个指向**另一个** host 的 envelope
    body = _envelope("https://k@evil.attacker.com/9")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as cli:
        r = await cli.post("/api/v1/sentry-tunnel", content=body)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_tunnel_rejects_bad_envelope(monkeypatch):
    """非法 envelope（第一行不是合法 JSON）→ 400。"""
    monkeypatch.setattr(st.settings, "sentry_dsn", "https://k@o1.ingest.us.sentry.io/2")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as cli:
        r = await cli.post("/api/v1/sentry-tunnel", content=b"not-json\nbody")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_tunnel_forwards_to_upstream_success(monkeypatch):
    """合法 envelope + host 匹配 → 透传到上游 → ok。"""
    monkeypatch.setattr(st.settings, "sentry_dsn", "https://k@o1.ingest.us.sentry.io/2")
    body = _envelope("https://k@o1.ingest.us.sentry.io/2")

    # mock httpx.AsyncClient.post 返回 200
    mock_resp = AsyncMock()
    mock_resp.status_code = 200

    class MockClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, **_kw):
            assert url == "https://o1.ingest.us.sentry.io/api/2/envelope/"
            return mock_resp

    monkeypatch.setattr(st.httpx, "AsyncClient", lambda **_kw: MockClient())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as cli:
        r = await cli.post("/api/v1/sentry-tunnel", content=body)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["upstream_status"] == 200


@pytest.mark.asyncio
async def test_tunnel_upstream_failed_does_not_5xx(monkeypatch):
    """上游挂了/超时 → 返回 upstream-failed，不抛 5xx（fire-and-forget）。"""
    monkeypatch.setattr(st.settings, "sentry_dsn", "https://k@o1.ingest.us.sentry.io/2")
    body = _envelope("https://k@o1.ingest.us.sentry.io/2")

    class BoomClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, *_a, **_kw):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(st.httpx, "AsyncClient", lambda **_kw: BoomClient())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as cli:
        r = await cli.post("/api/v1/sentry-tunnel", content=body)
    assert r.status_code == 200
    assert r.json() == {"status": "upstream-failed"}
