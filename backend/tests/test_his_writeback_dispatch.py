"""回写派发单测（his_adapter/writeback_dispatch.py）。

跨 worker 抢占逻辑：本地有 WS 连接直接执行；无连接广播指令，
超时无人抢占本地兜底；消费方仅在持有连接时抢占执行。
"""
import asyncio

import pytest

from app.his_adapter import writeback_dispatch as wd


@pytest.fixture
def local_bus(monkeypatch):
    """给派发模块换上进程内直投总线（隔离真实 Redis）。"""
    from app.his_adapter.event_bus import HisEventBus

    bus = HisEventBus()
    bus._unavailable = True
    monkeypatch.setattr(wd, "his_event_bus", bus)
    return bus


@pytest.fixture
def executed(monkeypatch):
    """打桩 _execute_and_report，记录调用参数。"""
    calls: list = []

    async def fake_execute(encounter_id, doctor_id):
        calls.append((encounter_id, doctor_id))

    monkeypatch.setattr(wd, "_execute_and_report", fake_execute)
    return calls


class _FakeManager:
    """可控的 ws_manager 替身。"""

    def __init__(self, connected: bool, visits: set = ()):  # noqa: B006
        self._connected = connected
        self._visits = set(visits)

    def has_connection(self) -> bool:
        return self._connected

    def has_visit(self, visit_no: str) -> bool:
        return visit_no in self._visits


@pytest.mark.asyncio
async def test_dispatch_local_connection_executes_directly(
    local_bus, executed, monkeypatch
):
    """本 worker 持有 WS 连接 → 直接执行，不广播指令。"""
    monkeypatch.setattr(wd, "his_ws_manager", _FakeManager(connected=True))
    await wd.dispatch_writeback("enc1", "doc1", "V1")
    assert executed == [("enc1", "doc1")]


@pytest.mark.asyncio
async def test_dispatch_no_connection_falls_back_locally(
    local_bus, executed, monkeypatch
):
    """无任何 worker 持有连接 → 广播后无人抢占 → 本地兜底执行（skipped 结果告知医生）。"""
    monkeypatch.setattr(wd, "his_ws_manager", _FakeManager(connected=False))
    monkeypatch.setattr(wd, "CLAIM_WAIT_SECONDS", 0.01)  # 缩短等待加速测试
    await wd.dispatch_writeback("enc2", "doc2", "V2")
    assert executed == [("enc2", "doc2")]


@pytest.mark.asyncio
async def test_consumer_without_connection_ignores(local_bus, executed, monkeypatch):
    """消费方无 WS 连接 → 不抢占不执行（让位给持有连接的 worker）。"""
    monkeypatch.setattr(wd, "his_ws_manager", _FakeManager(connected=False))
    await wd._maybe_execute({"req_id": "r1", "encounter_id": "e", "doctor_id": "d",
                             "visit_no": "V"})
    assert executed == []


@pytest.mark.asyncio
async def test_consumer_with_visit_binding_executes(local_bus, executed, monkeypatch):
    """消费方持有该就诊来源连接 → 立即抢占执行（无让位延迟）。"""
    monkeypatch.setattr(wd, "his_ws_manager",
                        _FakeManager(connected=True, visits={"V3"}))
    await wd._maybe_execute({"req_id": "r3", "encounter_id": "e3", "doctor_id": "d3",
                             "visit_no": "V3"})
    assert executed == [("e3", "d3")]


@pytest.mark.asyncio
async def test_consumer_non_source_worker_waits_then_executes(
    local_bus, executed, monkeypatch
):
    """消费方有连接但非来源诊室 → 让位延迟后仍无人抢占则执行。"""
    monkeypatch.setattr(wd, "his_ws_manager", _FakeManager(connected=True))
    monkeypatch.setattr(wd, "PREFER_DELAY_SECONDS", 0.01)
    await wd._maybe_execute({"req_id": "r4", "encounter_id": "e4", "doctor_id": "d4",
                             "visit_no": "V4"})
    assert executed == [("e4", "d4")]
