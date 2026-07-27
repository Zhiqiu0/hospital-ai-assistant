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
    his_ws_manager._ws = None  # 清理全局单例，避免污染其他用例
    his_ws_manager._pending.clear()


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
