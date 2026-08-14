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


# ── 2026-08-13 第二轮审计：降级不再是单向门 ────────────────────────────────

@pytest.mark.asyncio
async def test_local_fallback_emits_sentinel_for_resubscribe(monkeypatch):
    """Redis 不可用时的降级订阅必须定时投哨兵，促使消费方重建订阅。

    原实现降级后就地阻塞、永不再试 Redis——Redis 恢复后该 worker 永久收不到
    跨进程事件（回写指令 / 叫号），是个单向门。
    """
    from app.his_adapter import event_bus as eb

    # 把重试间隔压到极短，避免测试等 30 秒
    monkeypatch.setattr(eb, "LOCAL_FALLBACK_RETRY_SECONDS", 0.05)
    bus = eb.HisEventBus()
    # 模拟 Redis 不可用：publish 与 subscribe 现在用两个不同的客户端
    # （2026-08-14：订阅端不能设 socket_timeout，否则 pubsub 长阻塞会被误判
    # 为超时、订阅泵每 5 秒重建一次，生产日志实测到），两个入口都要置空
    monkeypatch.setattr(bus, "_get_client", lambda: None)
    monkeypatch.setattr(bus, "_get_sub_client", lambda: None)

    async with bus.subscription("ch-fallback") as q:
        evt = await asyncio.wait_for(q.get(), timeout=2)

    assert evt.get("type") == eb.PUMP_DEAD_SENTINEL


@pytest.mark.asyncio
async def test_local_fallback_still_delivers_events(monkeypatch):
    """降级期间进程内直投仍要正常工作（不能为了重试牺牲本地投递）。"""
    from app.his_adapter import event_bus as eb

    monkeypatch.setattr(eb, "LOCAL_FALLBACK_RETRY_SECONDS", 5)  # 本用例内不触发哨兵
    bus = eb.HisEventBus()
    monkeypatch.setattr(bus, "_get_client", lambda: None)
    monkeypatch.setattr(bus, "_get_sub_client", lambda: None)

    async with bus.subscription("ch-local") as q:
        await bus.publish("ch-local", {"type": "admit", "x": 1})
        evt = await asyncio.wait_for(q.get(), timeout=2)

    assert evt["type"] == "admit" and evt["x"] == 1
