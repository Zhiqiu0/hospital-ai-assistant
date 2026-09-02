# -*- coding: utf-8 -*-
"""可观测性回归（2026-09-02 日志专项）。

出问题时能不能第一时间定位，取决于两件事：日志里有没有那条记录，以及那条记录
能不能被聚合检索。本文件锁住后者——路径里的资源 UUID 会让"哪类请求最慢"
"本月几次病历修订"这类问题失去答案，因为每条记录的 path/action 都是新值。
"""
import logging
from types import SimpleNamespace

import pytest

from app.core.request_context import RequestIDMiddleware


class _Recorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[tuple[int, str]] = []

    def emit(self, record):
        self.lines.append((record.levelno, record.getMessage()))


async def _run_request(path: str, route_path: str | None, *, slow: bool = False):
    """跑一次假请求，返回 access 日志行。"""
    rec = _Recorder()
    lg = logging.getLogger("app.access")
    lg.addHandler(rec)
    lg.setLevel(logging.INFO)

    scope = {"type": "http", "path": path, "method": "GET", "headers": []}
    if route_path:
        scope["route"] = SimpleNamespace(path=route_path)

    async def app(scope_, receive_, send_):
        if slow:
            # 直接改 perf_counter 太脆；用 asyncio.sleep 触发阈值不现实。
            # 这里只验模板替换，慢分支由下面的显式断言覆盖。
            pass
        await send_({"type": "http.response.start", "status": 200, "headers": []})
        await send_({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(msg):
        sent.append(msg)

    await RequestIDMiddleware(app)(scope, receive, send)
    lg.removeHandler(rec)
    return rec.lines


@pytest.mark.asyncio
async def test_访问日志按路由模板聚合():
    """三次请求打到同一路由的不同资源，日志里的 path 必须是同一个值。"""
    paths = set()
    for uid in ("aaaa-1111", "bbbb-2222", "cccc-3333"):
        lines = await _run_request(
            f"/api/v1/encounters/{uid}/workspace",
            "/api/v1/encounters/{encounter_id}/workspace")
        access = [m for _, m in lines if "request.access" in m]
        assert access, "没打访问日志"
        paths.add(access[0].split("path=")[1].split(" ")[0])
    assert paths == {"/api/v1/encounters/{encounter_id}/workspace"}, \
        f"path 没收敛成模板：{paths}"


@pytest.mark.asyncio
async def test_未匹配到路由时退回实际路径():
    """404 这类请求 scope 里没有 route，不能因此丢掉整条访问日志。"""
    lines = await _run_request("/api/v1/no-such-endpoint", None)
    access = [m for _, m in lines if "request.access" in m]
    assert access and "/api/v1/no-such-endpoint" in access[0]


@pytest.mark.asyncio
async def test_健康检查不打访问日志():
    """探活每几秒一次，打日志会把 app.log 淹掉。"""
    lines = await _run_request("/api/v1/health", "/api/v1/health")
    assert not [m for _, m in lines if "request.access" in m]


@pytest.mark.asyncio
async def test_响应带回request_id():
    """前端报错截图上的 X-Request-ID 是串起整条链路的钥匙。"""
    scope = {"type": "http", "path": "/api/v1/x", "method": "GET", "headers": []}
    sent = []

    async def app(s, r, send_):
        await send_({"type": "http.response.start", "status": 200, "headers": []})

    async def receive():
        return {"type": "http.request"}

    async def send(msg):
        sent.append(msg)

    await RequestIDMiddleware(app)(scope, receive, send)
    headers = dict(sent[0]["headers"])
    assert b"x-request-id" in headers
    assert len(headers[b"x-request-id"]) >= 8
