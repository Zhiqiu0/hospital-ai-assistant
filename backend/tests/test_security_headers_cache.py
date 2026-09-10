# -*- coding: utf-8 -*-
"""API 响应禁缓存（2026-09-10 第 20 轮 HTTP 缓存面审计）。

抓的问题：API 的 JSON 响应此前没有任何 Cache-Control——患者列表/工作台
快照这类含 PHI 的响应可能被写进浏览器磁盘缓存；"共用诊室电脑"正是本系统
的威胁模型（登出清 localStorage 防的就是它，HTTP 缓存这条路漏了）。

口径：SecurityHeadersMiddleware 对所有响应 setdefault Cache-Control: no-store；
已显式声明缓存策略的端点（影像帧 private+max-age 的性能取舍）不被覆盖。
"""
import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient

from app.core.security_headers import SecurityHeadersMiddleware
from app.main import app as real_app


@pytest.mark.asyncio
async def test_真实应用的JSON响应带no_store():
    async with AsyncClient(transport=ASGITransport(app=real_app), base_url="http://t") as ac:
        r = await ac.get("/api/v1/health")
    assert r.headers.get("cache-control") == "no-store", (
        f"API 响应缺 no-store（实际：{r.headers.get('cache-control')!r}）——"
        "PHI JSON 会被共用电脑的浏览器磁盘缓存留存"
    )


@pytest.mark.asyncio
async def test_显式声明缓存策略的端点不被覆盖():
    """影像帧那类刻意的 private+max-age 性能取舍必须保留（setdefault 语义）。"""
    mini = FastAPI()
    mini.add_middleware(SecurityHeadersMiddleware)

    @mini.get("/cached")
    async def cached():
        return Response(content=b"x", media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=86400"})

    async with AsyncClient(transport=ASGITransport(app=mini), base_url="http://t") as ac:
        r = await ac.get("/cached")
    assert r.headers.get("cache-control") == "private, max-age=86400"
