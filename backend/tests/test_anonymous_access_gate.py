# -*- coding: utf-8 -*-
"""全端点匿名不可达门禁（2026-08-28 体检轮·永久性守卫）。

契约：除白名单（登录/健康检查/Sentry 隧道/用户名查重）外，**任何**路由
在不带 Authorization 的匿名请求下都不得返回 2xx。历史上多次审计抓到
"新增端点漏鉴权"（批量开户提权、export-audit 不校归属……），这类问题
以后由本测试在 CI 兜底：新端点忘了挂 get_current_user/验签，红灯。

断言口径选"非 2xx"而不是"必须 401"：不同守卫实现（JWT/验签/角色）
拒绝码不同（401/403/422 皆可），但"匿名拿到成功响应"永远是漏洞。
"""
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import app

# 设计上匿名可达的路由（新增前先想清楚为什么可以匿名，再来登记）
PUBLIC_PATHS = {
    "/api/v1/auth/login",          # 登录本身
    "/api/v1/auth/check-username", # 登录页用户名查重（有限流）
    "/api/v1/auth/logout",         # 无 token 时是幂等空操作（无副作用无泄露）
    "/api/v1/health",
    "/api/v1/health/deep",
    "/health",
    "/health/deep",
    "/api/v1/sentry-tunnel",       # 浏览器错误上报代理（登录前也要能报错）
}

# HIS 入站接口按规范用"信封式响应"：HTTP 恒 200，鉴权结果在业务码里
# （code=0 成功，非 0 拒绝）。对这些路由断言"匿名必须拿到非 0 业务码"。
HIS_ENVELOPE_PATHS = {
    "/api/v1/his/encounter/admit",
    "/api/v1/his/encounter/{encounter_id}/writeback",
}


@pytest_asyncio.fixture
async def anon_client(async_db) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_db] = lambda: async_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac
    app.dependency_overrides.clear()


def _fill_path(path: str) -> str:
    """把 {param} 占位填成假值——鉴权在参数解析前/中拒绝，值不重要。"""
    import re
    return re.sub(r"\{[^}]+\}", "x", path)


@pytest.mark.asyncio
async def test_no_route_serves_anonymous_2xx(anon_client):
    failures = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in PUBLIC_PATHS:
            continue
        method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
        url = _fill_path(route.path)
        kwargs = {}
        if method in ("POST", "PUT", "PATCH"):
            kwargs["json"] = {}
        resp = await anon_client.request(method, url, **kwargs)
        if route.path in HIS_ENVELOPE_PATHS:
            # 信封式：HTTP 200 合法，但业务码必须是拒绝（非 0）
            if resp.status_code == 200 and resp.json().get("code") == 0:
                failures.append(f"{method} {route.path} -> 信封 code=0（匿名验签通过）")
            continue
        if 200 <= resp.status_code < 300:
            failures.append(f"{method} {route.path} -> {resp.status_code}")
    assert not failures, (
        "以下路由匿名可达（漏鉴权或该进 PUBLIC_PATHS 白名单）：\n"
        + "\n".join(failures)
    )
