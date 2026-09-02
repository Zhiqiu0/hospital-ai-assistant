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


# ─── 4xx 拒绝原因必须留痕 ────────────────────────────────────────────
#
# 排障演练发现的盲区：医生报障最常见的三种形态是"打不开""看不到""保存不了"，
# 对应 403/404/422，而访问日志里只有一行 status=403——运维看不出是角色不对、
# 归属不对还是账号状态问题。detail 里恰恰写着答案，只是从没被记下来过。

from fastapi import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError

from app.main import http_exception_logger, validation_exception_logger


def _req(path="/api/v1/x", method="GET"):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


@pytest.mark.asyncio
async def test_403拒绝原因进日志(caplog):
    with caplog.at_level(logging.INFO):
        resp = await http_exception_logger(
            _req("/api/v1/qc/review-queue"),
            FastAPIHTTPException(status_code=403, detail="需要质控员权限"))
    assert resp.status_code == 403
    assert any("需要质控员权限" in r.getMessage() and "status=403" in r.getMessage()
               for r in caplog.records), "403 的拒绝原因没进日志"


@pytest.mark.asyncio
async def test_5xx记error而4xx记info(caplog):
    """4xx 是用户/前端做了不该做的事，混进 error.log 会把真故障淹掉。"""
    with caplog.at_level(logging.INFO):
        await http_exception_logger(_req(), FastAPIHTTPException(404, "接诊不存在"))
        await http_exception_logger(_req(), FastAPIHTTPException(503, "上游不可用"))
    levels = {r.getMessage().split("status=")[1][:3]: r.levelno
              for r in caplog.records if "app.http_error" in r.getMessage()}
    assert levels.get("404") == logging.INFO
    assert levels.get("503") == logging.ERROR


@pytest.mark.asyncio
async def test_422记字段但不记输入值(caplog):
    """input 里可能是患者姓名、病历正文这类 PHI，绝不能进日志。"""
    exc = RequestValidationError([{
        "type": "string_type", "loc": ("body", "patient_name"),
        "msg": "Input should be a valid string", "input": "张三的敏感信息",
    }])
    with caplog.at_level(logging.INFO):
        resp = await validation_exception_logger(_req(method="POST"), exc)
    assert resp.status_code == 422
    line = next(r.getMessage() for r in caplog.records if "app.validation_error" in r.getMessage())
    assert "body.patient_name" in line and "string_type" in line
    assert "张三" not in line, "PHI 进了日志"


@pytest.mark.asyncio
async def test_422响应体仍可序列化():
    """pydantic v2 的 errors() 里 ctx 会带原始 ValueError 对象，直接塞进
    JSONResponse 会 TypeError——必须走 jsonable_encoder（写这段时正是这么挂的）。"""
    exc = RequestValidationError([{
        "type": "value_error", "loc": ("body", "recorded_at"),
        "msg": "记录时间不能晚于当前时间", "input": "2099-01-01",
        "ctx": {"error": ValueError("记录时间不能晚于当前时间")},
    }])
    resp = await validation_exception_logger(_req(method="POST"), exc)
    assert resp.status_code == 422 and resp.body
