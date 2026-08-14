"""影像预热的 Redis 总量预算（2026-08-14 第八轮审计 medium）。

第五轮加的是**单张**上限，挡的是「单张巨图」；而真实主路径是「很多张中等大小
的图」：上传一份检查会对全部 instance 预热缩略图 + 1024 高清预览，一份 500 帧
的 CT 就是约 500 张预览（每张 100-200KB）+ 500 张缩略图，合计 60-110MB，
每张都在 512KB 以下全部畅通无阻，TTL 还是 7 天不会自然过期。

生产 Redis 是 256MB + allkeys-lru，且与正确性关键 key 共用同一实例：
两三份这样的检查填满后，LRU 会淘汰 his:wb:claim:*（→ 两个 worker 同时往 HIS
推同一份病历）、ratelimit:login:*（→ 登录爆破计数清零）、nonce:*（→ 防重放
与接诊去重失效）。影像缓存丢了只是重渲染一次，那些 key 丢了是正确性问题。
"""

import asyncio

import pytest

import app.services.pacs.render_cache as rc


@pytest.mark.asyncio
async def test_大检查预热不会写爆redis(monkeypatch):
    """500 帧 CT：修复前会写 60MB+，现在受总预算封顶。"""
    written: list[int] = []

    async def _fake_set_bytes(key, payload, ttl=None):
        written.append(len(payload))

    monkeypatch.setattr(rc.redis_cache, "set_bytes", _fake_set_bytes)
    # 渲染换成固定大小的假数据，避免依赖 pydicom
    monkeypatch.setattr(rc, "render_thumbnail", lambda b: b"t" * 20_000)      # 20KB
    monkeypatch.setattr(rc, "render_preview", lambda b: b"p" * 150_000)       # 150KB

    instances = [(f"iuid-{i}", b"dcm") for i in range(500)]
    await rc.render_and_cache_all("study-1", instances)

    total = sum(written)
    assert total <= rc._MAX_PREWARM_TOTAL_BYTES, (
        f"预热写了 {total/1024/1024:.1f}MB，超出预算 "
        f"{rc._MAX_PREWARM_TOTAL_BYTES/1024/1024:.0f}MB"
    )
    # 预算内的前若干帧仍要被缓存（医生大多只看前几张），不能一刀切不缓存
    assert written, "一张都没缓存，预热等于白做"


@pytest.mark.asyncio
async def test_小检查完整缓存不受影响(monkeypatch):
    """防过度收紧：常规几十帧的检查应当全部缓存。"""
    written: list[str] = []

    async def _fake_set_bytes(key, payload, ttl=None):
        written.append(key)

    monkeypatch.setattr(rc.redis_cache, "set_bytes", _fake_set_bytes)
    monkeypatch.setattr(rc, "render_thumbnail", lambda b: b"t" * 20_000)
    monkeypatch.setattr(rc, "render_preview", lambda b: b"p" * 150_000)

    instances = [(f"iuid-{i}", b"dcm") for i in range(20)]
    await rc.render_and_cache_all("study-2", instances)

    # 20 帧 × (缩略 + 预览) = 40 个 key，总量约 3.4MB，远在预算内
    assert len(written) == 40


@pytest.mark.asyncio
async def test_单张超限仍然不进缓存(monkeypatch):
    """第五轮那条单张上限不能被这次改动弄丢。"""
    written: list[str] = []

    async def _fake_set_bytes(key, payload, ttl=None):
        written.append(key)

    monkeypatch.setattr(rc.redis_cache, "set_bytes", _fake_set_bytes)
    monkeypatch.setattr(rc, "render_thumbnail", lambda b: b"t" * 10)
    monkeypatch.setattr(rc, "render_preview", lambda b: b"p" * (rc._MAX_CACHEABLE_BYTES + 1))

    await rc.render_and_cache_all("study-3", [("iuid-0", b"dcm")])

    assert any("thumb" in k for k in written)
    assert not any("preview" in k for k in written), "超过单张上限的预览图仍被缓存了"
