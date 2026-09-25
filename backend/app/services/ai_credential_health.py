"""AI鉴权探活：短缓存的免费余额接口，区分配置存在与实际可用。"""
import asyncio
import hashlib
import logging
import time
from urllib.parse import urlsplit

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class CredentialHealthProbe:
    """每个worker最多每分钟探测一次，并合并同时到达的监控请求。

    只支持明确的DeepSeek官方鉴权协议；兼容服务没有同一协议时返回未验证。
    不返回账户余额、供应商响应正文或密钥。此探针不证明模型输出质量。
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._loop = None
        self._fingerprint = ''
        self._expires_at = 0.0
        self._status = 'unverified'

    async def check(self, base_url: str, api_key: str) -> str:
        """配置变动立即失效旧缓存；未知供应商不能把密钥发到官方地址。"""
        if not api_key:
            return 'missing'
        try:
            parsed = urlsplit(base_url)
        except ValueError:
            # 配置格式错误也返回明确状态，不能让整个深度探活异常退出。
            return 'unverified'
        if (parsed.scheme != 'https' or parsed.netloc != 'api.deepseek.com'
                or parsed.path.rstrip('/') not in ('', '/v1') or parsed.query):
            return 'unverified'
        fingerprint = hashlib.sha256(f'{base_url}\0{api_key}'.encode()).hexdigest()
        # lifespan重建后不复用旧循环的锁；同一worker循环内仍合并并发请求。
        loop = asyncio.get_running_loop()
        if self._loop is not loop:
            self._loop = loop
            self._lock = asyncio.Lock()
        async with self._lock:
            if fingerprint == self._fingerprint and time.monotonic() < self._expires_at:
                return self._status
            status = await self._request(api_key)
            self._fingerprint = fingerprint
            self._expires_at = time.monotonic() + 60
            self._status = status
            return status

    @staticmethod
    async def _request(api_key: str) -> str:
        """使用不消耗生成token的官方接口，超时与错误结构均不能报绿。"""
        try:
            async with asyncio.timeout(4):
                async with httpx.AsyncClient(timeout=3.0, follow_redirects=False) as client:
                    response = await client.get(
                        'https://api.deepseek.com/user/balance',
                        headers={'Authorization': f'Bearer {api_key}'},
                    )
            if response.status_code in (401, 403):
                return 'invalid'
            if response.status_code != 200:
                return 'error'
            body = response.json()
            available = body.get('is_available') if isinstance(body, dict) else None
            if available is True:
                return 'ok'
            return 'unavailable' if available is False else 'error'
        except (httpx.HTTPError, TimeoutError, ValueError):
            logger.warning('health.ai_credential: 供应商鉴权探测失败')
            return 'error'


credential_probe = CredentialHealthProbe()


async def check_ai_credential() -> str:
    """深度健康检查入口；基础存活检查不受上游波动影响。"""
    return await credential_probe.check(settings.deepseek_base_url, settings.deepseek_api_key)
