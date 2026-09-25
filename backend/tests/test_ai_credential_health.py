"""深度探活必须验证上游鉴权；模拟网络边界，不调用真实供应商。"""
import json
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.fixture
def healthy_dependencies(monkeypatch):
    """固定无关依赖为健康，避免数据库/日历掩盖AI探针错误。"""
    import app.main as main
    import app.database as database
    from app.config import settings
    from app.services.redis_cache import redis_cache
    from app.services.orthanc_client import orthanc_client
    from app.services import workdays
    from app.services import ai_credential_health

    class Result:
        def scalar(self):
            return datetime.now()

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args):
            return Result()

    class Engine:
        def connect(self):
            return Session()

    monkeypatch.setattr(main, 'AsyncSessionLocal', Session)
    monkeypatch.setattr(database, 'engine', Engine())
    monkeypatch.setattr(redis_cache, '_get_client', lambda: None)
    monkeypatch.setattr(orthanc_client, 'health_check', AsyncMock(return_value=True))
    monkeypatch.setattr(workdays, 'calendar_status', lambda: ('ok', 90))
    monkeypatch.setattr(settings, 'deepseek_base_url', 'https://api.deepseek.com')
    monkeypatch.setattr(ai_credential_health, 'credential_probe', ai_credential_health.CredentialHealthProbe())
    return main, settings


@pytest.mark.parametrize(('upstream', 'body', 'expected'), [
    (401, {}, 'invalid'),
    (403, {}, 'invalid'),
    (200, {'is_available': False}, 'unavailable'),
    (503, {}, 'error'),
    (200, {'wrong_shape': True}, 'error'),
    (200, {'is_available': True}, 'ok'),
])
async def test_deep_health_uses_authenticated_probe(healthy_dependencies, monkeypatch, upstream, body, expected):
    """非空密钥不等于可用；不向匿名探活泄露余额或密钥。"""
    main, settings = healthy_dependencies
    monkeypatch.setattr(settings, 'deepseek_api_key', f'test-probe-{upstream}-{expected}')
    get = AsyncMock(return_value=httpx.Response(upstream, json=body))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    response = await main.health_check_deep()
    data = json.loads(response.body)
    assert data['deps']['ai_credential'] == expected
    assert response.status_code == (200 if expected == 'ok' else 503)
    get.assert_awaited_once()
    assert settings.deepseek_api_key not in response.body.decode()
    assert 'balance_infos' not in data


async def test_probe_timeout_is_bounded_and_not_green(healthy_dependencies, monkeypatch):
    """供应商超时必须显示未知故障，不能继续沿用配置存在的绿灯。"""
    main, settings = healthy_dependencies
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-timeout')
    monkeypatch.setattr(httpx.AsyncClient, 'get', AsyncMock(side_effect=httpx.ReadTimeout('test')))
    response = await main.health_check_deep()
    assert json.loads(response.body)['deps']['ai_credential'] == 'error'
    assert response.status_code == 503


async def test_missing_key_skips_network(healthy_dependencies, monkeypatch):
    """缺凭据无需网络调用即可确定失败。"""
    main, settings = healthy_dependencies
    monkeypatch.setattr(settings, 'deepseek_api_key', '')
    get = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    response = await main.health_check_deep()
    assert json.loads(response.body)['deps']['ai_credential'] == 'missing'
    get.assert_not_awaited()


@pytest.mark.parametrize('base_url', ['https://example.invalid/v1', 'https://[invalid'])
async def test_custom_provider_is_explicitly_unverified(healthy_dependencies, monkeypatch, base_url):
    """兼容供应商无余额协议时不乱发密钥，也不宣称已验证。"""
    main, settings = healthy_dependencies
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-custom')
    monkeypatch.setattr(settings, 'deepseek_base_url', base_url)
    get = AsyncMock()
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    response = await main.health_check_deep()
    assert json.loads(response.body)['deps']['ai_credential'] == 'unverified'
    assert json.loads(response.body)['status'] == 'degraded'
    assert response.status_code == 503
    get.assert_not_awaited()


async def test_consecutive_checks_reuse_short_cache(healthy_dependencies, monkeypatch):
    """匿名监控频繁轮询不能无界放大供应商请求。"""
    main, settings = healthy_dependencies
    monkeypatch.setattr(settings, 'deepseek_api_key', 'test-cache')
    get = AsyncMock(return_value=httpx.Response(200, json={'is_available': True}))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    await main.health_check_deep()
    await main.health_check_deep()
    get.assert_awaited_once()


def test_probe_reused_across_lifespans_coalesces_requests(monkeypatch):
    """重启异步生命周期后仍可合并并发探测，锁不得绑定已关闭的循环。"""
    import asyncio
    from app.services.ai_credential_health import CredentialHealthProbe

    probe = CredentialHealthProbe()
    calls = []

    async def request(key):
        calls.append(key)
        await asyncio.sleep(0.01)
        return 'ok'

    monkeypatch.setattr(probe, '_request', request)

    async def batch(key):
        return await asyncio.gather(*(probe.check('https://api.deepseek.com', key) for _ in range(3)))

    assert asyncio.run(batch('first-test-key')) == ['ok'] * 3
    assert asyncio.run(batch('rotated-test-key')) == ['ok'] * 3
    assert calls == ['first-test-key', 'rotated-test-key']
