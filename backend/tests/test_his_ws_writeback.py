"""回写走 WebSocket 通道的单测：通道选择、ack 判定、超时重发耗尽。"""
import json

import pytest

from app.config import settings
from app.his_adapter import ws_protocol as wp
from app.his_adapter import writeback_sender as sender_module
from app.his_adapter.ws_manager import HisWsManager, his_ws_manager
from app.his_adapter.writeback_sender import send_writeback

FAKE_PAYLOAD = {"visit_id": "V1", "record_type": "outpatient",
                "record": {"chief_complaint": "头晕3天"}}


class AckingWS:
    """假 HIS 连接：收到消息立刻回 ack（code=0），记录收到的每条消息。"""

    def __init__(self, manager):
        self.manager = manager
        self.sent: list[dict] = []
        self.closed = False

    async def send_text(self, text: str):
        env = json.loads(text)
        self.sent.append(env)
        self.manager.resolve_ack(
            env["msg_id"],
            {"code": 0, "message": "ok", "data": {"record_id": "DOC-1"}},
        )

    async def close(self):
        self.closed = True


class DeafWS(AckingWS):
    """装死的连接：只收不 ack，用于测超时重发耗尽。"""

    async def send_text(self, text: str):
        self.sent.append(json.loads(text))


@pytest.fixture
def ws_creds(monkeypatch):
    monkeypatch.setattr(settings, "his_inbound_app_id", "appHIS")
    monkeypatch.setattr(settings, "his_inbound_app_secret", "secret-key")
    # payload 构建打桩：绕开数据库，专测传输层
    async def fake_build(db, encounter_id, app_version="1.0.0"):
        return dict(FAKE_PAYLOAD)
    monkeypatch.setattr(sender_module, "build_writeback_payload", fake_build)
    yield
    # 清理全局单例，避免污染其他用例
    his_ws_manager._conns.clear()
    his_ws_manager._pending.clear()
    his_ws_manager._visit_conn.clear()


@pytest.mark.asyncio
async def test_writeback_prefers_ws_channel(ws_creds):
    """WS 在线 → 回写走长连接：先 record_writeback 再 record_refresh，成功返回。"""
    fake = AckingWS(his_ws_manager)
    his_ws_manager.register(fake)
    result = await send_writeback(db=None, encounter_id="E1")
    assert result.ok and result.status == "success"
    assert result.his_doc_id == "DOC-1"
    types = [m["type"] for m in fake.sent]
    assert types == [wp.MSG_WRITEBACK, wp.MSG_REFRESH]
    # 刷新消息按规范带 visit_id + target
    refresh_payload = fake.sent[1]["payload"]
    assert refresh_payload == {"visit_id": "V1", "target": "outpatient_record"}


@pytest.mark.asyncio
async def test_writeback_routes_to_visit_origin_connection(ws_creds):
    """多诊室并存时：回写优先发回该就诊的接诊来源连接（那台诊室才需要刷新界面）。"""
    other = AckingWS(his_ws_manager)   # 别的诊室
    origin = AckingWS(his_ws_manager)  # 本次就诊的接诊来源诊室
    his_ws_manager.register(other)
    his_ws_manager.register(origin)
    his_ws_manager.bind_visit("V1", origin)  # 模拟 V1 的接诊推送来自 origin
    result = await send_writeback(db=None, encounter_id="E1")
    assert result.ok
    assert [m["type"] for m in origin.sent] == [wp.MSG_WRITEBACK, wp.MSG_REFRESH]
    assert other.sent == []  # 别的诊室一条都不该收到


@pytest.mark.asyncio
async def test_writeback_falls_back_when_origin_gone(ws_creds):
    """来源诊室断线后：回写退回任一在线连接，落库不丢（刷新由医生重开兜底）。"""
    origin = AckingWS(his_ws_manager)
    backup = AckingWS(his_ws_manager)
    his_ws_manager.register(origin)
    his_ws_manager.register(backup)
    his_ws_manager.bind_visit("V1", origin)
    his_ws_manager.unregister(origin)  # 来源诊室下线
    result = await send_writeback(db=None, encounter_id="E1")
    assert result.ok
    assert [m["type"] for m in backup.sent] == [wp.MSG_WRITEBACK, wp.MSG_REFRESH]


@pytest.mark.asyncio
async def test_writeback_skipped_when_no_channel(ws_creds, monkeypatch):
    """WS 离线且 HTTP 地址未配置 → skipped 安全空跑（联调前状态）。"""
    monkeypatch.setattr(settings, "his_writeback_url", "")
    result = await send_writeback(db=None, encounter_id="E1")
    assert result.status == "skipped"


@pytest.mark.asyncio
async def test_ws_ack_timeout_exhausts_and_closes(ws_creds, monkeypatch):
    """对面不 ack → 超时重发耗尽（同 msg_id 共 1+3 次）→ 连接判死关闭。"""
    monkeypatch.setattr(wp, "ACK_TIMEOUT", 0.01)  # 缩短超时加速测试
    manager = HisWsManager()
    deaf = DeafWS(manager)
    manager.register(deaf)
    with pytest.raises(ConnectionError):
        await manager.send_with_ack(wp.MSG_WRITEBACK, FAKE_PAYLOAD, "appHIS", "secret-key")
    assert len(deaf.sent) == 1 + wp.ACK_MAX_RESEND  # 首发 + 3 次重发
    assert len({m["msg_id"] for m in deaf.sent}) == 1  # msg_id 不变
    signs = {m["sign"] for m in deaf.sent}
    assert len(signs) >= 2  # 每次重发重新生成 nonce/sign（同 2.2 重试规则）
    assert deaf.closed and not manager.has_connection()


@pytest.mark.asyncio
async def test_ws_write_failed_code_propagates(ws_creds):
    """厂商 ack code!=0 → write_failed，且不再发刷新消息。"""
    manager_ws = AckingWS(his_ws_manager)

    async def nack(text: str):
        env = json.loads(text)
        manager_ws.sent.append(env)
        his_ws_manager.resolve_ack(env["msg_id"], {"code": 40005, "message": "找不到就诊"})

    manager_ws.send_text = nack
    his_ws_manager.register(manager_ws)
    result = await send_writeback(db=None, encounter_id="E1")
    assert not result.ok and result.status == "write_failed"
    assert "40005" in result.message
    assert [m["type"] for m in manager_ws.sent] == [wp.MSG_WRITEBACK]


# ── 2026-08-13 第二轮审计：僵尸连接换线 ────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_failover_to_healthy_connection(ws_creds, monkeypatch):
    """来源诊室连接变僵尸时，自动换到另一条在线连接，而不是直接报失败。

    原实现只在被选中的那条连接上重发，耗尽即 ConnectionError——网络闪断后的
    连接要 90s 才被空闲超时摘除，期间还会被优先选中（它是来源诊室连接），
    于是回写空耗 40s 后误报失败，哪怕院内还有别的在线诊室。
    """
    monkeypatch.setattr(wp, "ACK_TIMEOUT", 0.01)
    manager = HisWsManager()
    zombie = DeafWS(manager)      # 闪断后的僵尸：只收不 ack
    healthy = AckingWS(manager)   # 另一台在线诊室
    manager.register(zombie)
    manager.register(healthy)
    manager.bind_visit("V-ZOMBIE", zombie)  # 僵尸是来源诊室，会被优先选中

    ack = await manager.send_with_ack(
        wp.MSG_WRITEBACK, FAKE_PAYLOAD, "appHIS", "secret-key",
        prefer_visit="V-ZOMBIE",
    )

    assert ack["code"] == 0              # 换线后成功，不再误报失败
    assert zombie.closed                 # 僵尸被判死并摘除
    assert healthy.sent                  # 消息确实由健康连接发出


@pytest.mark.asyncio
async def test_ws_failover_all_dead_still_raises(ws_creds, monkeypatch):
    """所有连接都失效时仍要如实抛错（不能为了换线把失败吞掉）。"""
    monkeypatch.setattr(wp, "ACK_TIMEOUT", 0.01)
    manager = HisWsManager()
    manager.register(DeafWS(manager))
    manager.register(DeafWS(manager))

    with pytest.raises(ConnectionError):
        await manager.send_with_ack(wp.MSG_WRITEBACK, FAKE_PAYLOAD, "appHIS", "secret-key")
    assert not manager.has_connection()
