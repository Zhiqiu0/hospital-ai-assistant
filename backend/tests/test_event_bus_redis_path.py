# -*- coding: utf-8 -*-
"""HIS 事件总线的 Redis 真路径测试（2026-09-19 补——终检覆盖率头号盲区）。

背景：生产是 2 worker + Redis pubsub，但既有测试全部走"未配置 Redis"的
进程内直投——「签发 → 跨 worker 回写 HIS」的生产形态零覆盖。这里用
fakeredis（共享 FakeServer 模拟两个 worker 各自的连接）把四条命脉补上：
  · 跨 worker pubsub 投递（生产主路径）
  · 泵死哨兵（Redis 断连时订阅方必须感知，不能假活）
  · try_claim 的 SET NX 抢占（防两 worker 同时往院方 HIS 推同一份病历）
  · try_claim fail-closed（Redis 报错必须判"未抢到"——第二轮审计原则：
    有对外副作用的降级一律 fail-closed）
"""
import asyncio

import fakeredis.aioredis
import pytest

from app.his_adapter.event_bus import PUMP_DEAD_SENTINEL, HisEventBus


@pytest.fixture
def two_workers(monkeypatch):
    """同一 FakeServer 上的两条连接——模拟 worker A / worker B。"""
    server = fakeredis.FakeServer()

    def _bus():
        bus = HisEventBus()
        client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
        monkeypatch.setattr(bus, "_get_client", lambda: client)
        monkeypatch.setattr(bus, "_get_sub_client", lambda: client)
        return bus

    return _bus(), _bus()


@pytest.mark.asyncio
async def test_跨worker_pubsub投递(two_workers):
    bus_a, bus_b = two_workers
    async with bus_a.subscription("his:test") as q:
        await asyncio.sleep(0.05)  # 等泵任务真正进入 listen
        await bus_b.publish("his:test", {"type": "writeback", "encounter_id": "e1"})
        event = await asyncio.wait_for(q.get(), timeout=2)
    assert event["encounter_id"] == "e1", "worker B 发布的事件必须经 Redis 到达 worker A"


@pytest.mark.asyncio
async def test_泵死投哨兵_订阅方不假活(monkeypatch):
    """订阅建立后 Redis 断连（listen 迭代抛异常）→ 必须收到哨兵而不是死寂。"""

    class _DyingPubSub:
        async def subscribe(self, ch):
            pass

        async def unsubscribe(self, ch):
            pass

        async def aclose(self):
            pass

        async def listen(self):
            # 先送一条正常消息证明泵活过，再模拟断连
            yield {"type": "message", "data": '{"type": "normal"}'}
            raise ConnectionError("redis gone")

    class _SubClient:
        def pubsub(self):
            return _DyingPubSub()

    bus = HisEventBus()
    monkeypatch.setattr(bus, "_get_sub_client", lambda: _SubClient())
    async with bus.subscription("his:test") as q:
        first = await asyncio.wait_for(q.get(), timeout=2)
        assert first == {"type": "normal"}
        sentinel = await asyncio.wait_for(q.get(), timeout=2)
    assert sentinel.get("type") == PUMP_DEAD_SENTINEL, (
        "泵死后订阅方必须收到哨兵——否则 SSE 假活、回写消费永久失聪")


@pytest.mark.asyncio
async def test_claim抢占_只有一个worker赢(two_workers):
    bus_a, bus_b = two_workers
    a = await bus_a.try_claim("his:wb:claim:req1", ttl=30)
    b = await bus_b.try_claim("his:wb:claim:req1", ttl=30)
    assert (a, b) == (True, False), "同一回写指令只能有一个 worker 抢到（防双推 HIS）"
    # 不同指令互不影响
    assert await bus_b.try_claim("his:wb:claim:req2", ttl=30) is True


@pytest.mark.asyncio
async def test_claim_fail_closed(two_workers, monkeypatch):
    bus_a, _ = two_workers

    class _Boom:
        async def set(self, *a, **k):
            raise ConnectionError("redis down")

    monkeypatch.setattr(bus_a, "_get_client", lambda: _Boom())
    assert await bus_a.try_claim("his:wb:claim:req3", ttl=30) is False, (
        "Redis 报错必须判未抢到（fail-closed）——返回 True 就是两 worker 同时推 HIS")


@pytest.mark.asyncio
async def test_publish_redis失败落本地直投(two_workers, monkeypatch):
    """Redis 挂掉的 worker 自己进程内的订阅者仍要收到事件（降级不失聪）。"""
    bus_a, _ = two_workers

    class _PubBoom:
        async def publish(self, *a, **k):
            raise ConnectionError("redis down")

    # 订阅走本地直投（sub client 也判不可用）
    monkeypatch.setattr(bus_a, "_get_sub_client", lambda: None)
    async with bus_a.subscription("his:test") as q:
        monkeypatch.setattr(bus_a, "_get_client", lambda: _PubBoom())
        await bus_a.publish("his:test", {"type": "writeback", "encounter_id": "e9"})
        event = await asyncio.wait_for(q.get(), timeout=2)
    assert event["encounter_id"] == "e9"
