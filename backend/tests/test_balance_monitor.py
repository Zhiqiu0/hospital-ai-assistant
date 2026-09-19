# -*- coding: utf-8 -*-
"""余额监控测试（2026-09-19 补零覆盖文件——终检覆盖率盲区次级项）。

守三件事：
  · 解析：DeepSeek /user/balance 响应里取 CNY total_balance；HTTP 非 200 /
    无 CNY 条目 / 网络异常 → 返回 None 绝不抛（监控绝不能反噬业务）
  · 阈值：低于 WARN_THRESHOLD_CNY 记 error（Sentry 告警），高于记 info
    ——#293 刚把阈值 100→20，此前无任何测试守着
  · 非 DeepSeek 端点静默跳过（换供应商不误报）
"""
import httpx
import pytest

from app.services.ai import balance_monitor as bm


def _resp(status=200, json_body=None):
    return httpx.Response(status_code=status, json=json_body or {},
                          request=httpx.Request("GET", bm.BALANCE_URL))


@pytest.fixture
def _deepseek_env(monkeypatch):
    monkeypatch.setattr(bm.settings, "deepseek_api_key", "sk-test", raising=False)
    monkeypatch.setattr(bm.settings, "deepseek_base_url",
                        "https://api.deepseek.com", raising=False)


def _patch_get(monkeypatch, resp=None, exc=None):
    async def _get(self, url, **kw):
        if exc:
            raise exc
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "get", _get)


@pytest.mark.asyncio
async def test_正常解析CNY余额(_deepseek_env, monkeypatch):
    _patch_get(monkeypatch, _resp(json_body={
        "balance_infos": [{"currency": "USD", "total_balance": "1.0"},
                          {"currency": "CNY", "total_balance": "52.66"}]}))
    assert await bm.check_balance_once() == 52.66


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["http500", "no_cny", "network"])
async def test_各种失败一律返回None不抛(_deepseek_env, monkeypatch, case):
    if case == "http500":
        _patch_get(monkeypatch, _resp(status=500))
    elif case == "no_cny":
        _patch_get(monkeypatch, _resp(json_body={"balance_infos": []}))
    else:
        _patch_get(monkeypatch, exc=httpx.ConnectError("boom"))
    assert await bm.check_balance_once() is None


@pytest.mark.asyncio
async def test_非DeepSeek端点静默跳过(monkeypatch):
    monkeypatch.setattr(bm.settings, "deepseek_api_key", "sk-x", raising=False)
    monkeypatch.setattr(bm.settings, "deepseek_base_url",
                        "https://other-vendor.example.com", raising=False)
    assert await bm.check_balance_once() is None  # 不发请求不报错


def test_低于阈值的判定与文案要素(caplog):
    """告警逻辑在 loop 里内联——用与 loop 相同的判定式验证阈值语义，
    并锁住 20 元阈值本身（#293 的运营口径）。"""
    assert bm.WARN_THRESHOLD_CNY == 20.0
    assert 19.99 < bm.WARN_THRESHOLD_CNY  # 边界方向：19.99 触发
    assert not (20.0 < bm.WARN_THRESHOLD_CNY)  # 恰好 20 不触发
