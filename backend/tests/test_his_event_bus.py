"""HIS 事件总线单测（进程内直投模式；Redis 模式靠生产冒烟验证）。"""
import asyncio

import pytest

from app.his_adapter.event_bus import HisEventBus


@pytest.fixture
def local_bus(monkeypatch):
    """强制走进程内直投（模拟 Redis 未配置）。"""
    bus = HisEventBus()
    bus._unavailable = True  # 跳过建连直接进入本地模式
    return bus


@pytest.mark.asyncio
async def test_publish_delivered_to_subscriber(local_bus):
    """订阅后发布 → 队列收到同一事件。"""
    async with local_bus.subscription("ch1") as q:
        await local_bus.publish("ch1", {"type": "admit", "visit_no": "V1"})
        event = await asyncio.wait_for(q.get(), timeout=1)
        assert event == {"type": "admit", "visit_no": "V1"}


@pytest.mark.asyncio
async def test_publish_other_channel_not_delivered(local_bus):
    """发布到别的频道 → 本订阅收不到。"""
    async with local_bus.subscription("ch1") as q:
        await local_bus.publish("ch2", {"type": "admit"})
        assert q.empty()


@pytest.mark.asyncio
async def test_subscription_cleanup(local_bus):
    """退出订阅上下文后 → 注册表清理，后续发布不再投递。"""
    async with local_bus.subscription("ch1") as q:
        pass
    await local_bus.publish("ch1", {"type": "x"})
    assert q.empty()
    assert not local_bus._local.get("ch1")


@pytest.mark.asyncio
async def test_claim_without_redis_always_true(local_bus):
    """无 Redis 时抢占恒为 True（进程内无并发抢占）、is_claimed 恒 False。"""
    assert await local_bus.try_claim("k1", ttl=60) is True
    assert await local_bus.is_claimed("k1") is False
