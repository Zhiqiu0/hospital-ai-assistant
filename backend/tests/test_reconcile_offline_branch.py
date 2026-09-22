# -*- coding: utf-8 -*-
"""对账"HIS 整体离线不放弃"分支回归锁（2026-09-16 覆盖率盲区 #2）。

背景：2026-08-13 第五轮审计修复——status='skipped'（WS 与 HTTP 都不在线
= HIS 整体离线）达到重试上限时**不得**标记 exhausted 永久放弃，而要告警+
重置计数继续重试，等 HIS 恢复自动补上；否则 HIS 停机半小时就把全院当天
病历静默标成永久放弃，对账存在的全部意义被废掉。该修复此前无回归锁。

对照组：status='failed'（真推过但对方拒收）达上限 → 照旧标 exhausted
停止自动重投（需人工处理）——两个分支的分野正是本修复的全部语义。
"""
from datetime import datetime

import pytest

from app.his_adapter import writeback_reconcile as wr
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient


class _SameSession:
    """让模块内 AsyncSessionLocal() 复用测试会话（SQLite :memory: 新连接是
    独立空库——与降级演练测试同一手法）。"""

    def __init__(self, db):
        self._db = db

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


async def _mk_candidate(db, *, wb_status: str, attempts: int) -> str:
    p = Patient(name="对账", gender="male")
    db.add(p)
    await db.flush()
    enc = Encounter(
        patient_id=p.id, doctor_id="doc-1", visit_type="outpatient",
        visit_no="RC-001", visited_at=datetime.now(),
        his_external_ref={
            "source": "admit_push", "hospital_code": "H1",
            "his_visit_no": "RC-001",
            "writeback_records": {
                "outpatient:1": {"status": wb_status, "reconcile_attempts": attempts},
            },
        },
    )
    db.add(enc)
    await db.flush()
    rec = MedicalRecord(encounter_id=enc.id, record_type="outpatient",
                        status="submitted", submitted_at=datetime.now(),
                        current_version=1, record_no=1)
    db.add(rec)
    await db.flush()
    db.add(RecordVersion(medical_record_id=rec.id, version_no=1,
                         content={"text": "正文"}, source="manual"))
    await db.commit()
    return enc.id


def _entry(enc):
    return ((enc.his_external_ref or {}).get("writeback_records") or {}).get("outpatient:1") or {}


@pytest.mark.asyncio
async def test_HIS整体离线达上限_重置计数继续重试不放弃(async_db, monkeypatch):
    import app.database as app_db
    monkeypatch.setattr(app_db, "AsyncSessionLocal", _SameSession(async_db))

    sent = []

    async def _no_send(db, enc_id, record_id=None):
        sent.append(enc_id)

    monkeypatch.setattr("app.his_adapter.writeback_sender.send_writeback", _no_send)

    enc_id = await _mk_candidate(async_db, wb_status="skipped",
                                 attempts=wr.MAX_RECONCILE_ATTEMPTS)
    await wr.reconcile_once()

    async_db.expire_all()
    enc = await async_db.get(Encounter, enc_id)
    e = _entry(enc)
    assert e.get("reconcile_attempts") == 0, (
        f"离线分支必须重置计数继续重试，实际 {e}——HIS 恢复后将永不补推")
    assert e.get("status") == "skipped", "不得改判 exhausted（那是永久放弃）"
    assert not sent, "HIS 离线时本轮不应硬发（等下一轮恢复后再投）"


@pytest.mark.asyncio
async def test_真失败达上限_照旧标exhausted停止重投(async_db, monkeypatch):
    """对照组：write_failed 是"推过但对方拒收"，重试无意义，需人工——不能被
    离线分支的宽大处理误伤。"""
    import app.database as app_db
    monkeypatch.setattr(app_db, "AsyncSessionLocal", _SameSession(async_db))
    monkeypatch.setattr("app.his_adapter.writeback_sender.send_writeback",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应发送")))

    enc_id = await _mk_candidate(async_db, wb_status="write_failed",
                                 attempts=wr.MAX_RECONCILE_ATTEMPTS)
    await wr.reconcile_once()

    async_db.expire_all()
    enc = await async_db.get(Encounter, enc_id)
    e = _entry(enc)
    assert e.get("reconcile_exhausted") is True or e.get("status") == "exhausted" or e.get("exhausted"), (
        f"真失败达上限必须标耗尽停手，实际 {e}")


@pytest.mark.asyncio
async def test_本进程无连接_重投改走跨worker广播且预计数(async_db, monkeypatch):
    """跨 worker 盲区回归锁（2026-09-23 复检彩排实锤）。

    生产 --workers 2：厂商 WS 连接与对账锁各自随机落进程，异进程时旧实现
    本地直调 send_writeback 恒得 skipped——"5 分钟内自动补投"承诺失效。
    修复语义：本进程无连接且未配 HTTP 回落地址 → ①先 +1 计数（保 exhausted
    可达，执行成功由 sender 落库清零）；②改走 dispatch_writeback 广播给持
    连接的 worker；③绝不本地直调 send_writeback。
    """
    import app.database as app_db
    monkeypatch.setattr(app_db, "AsyncSessionLocal", _SameSession(async_db))

    # 场景固定为"本进程无连接、无 HTTP 回落"
    monkeypatch.setattr(wr.his_ws_manager, "has_connection", lambda: False)
    monkeypatch.setattr(wr.settings, "his_writeback_url", "", raising=False)

    dispatched = []

    async def _fake_dispatch(encounter_id, doctor_id, visit_no, record_id=None):
        dispatched.append((encounter_id, doctor_id, visit_no, record_id))

    monkeypatch.setattr("app.his_adapter.writeback_dispatch.dispatch_writeback",
                        _fake_dispatch)
    monkeypatch.setattr(
        "app.his_adapter.writeback_sender.send_writeback",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("异进程时不得本地直调")))

    enc_id = await _mk_candidate(async_db, wb_status="write_failed", attempts=1)
    await wr.reconcile_once()

    assert len(dispatched) == 1, "必须恰好广播一次跨 worker 重投"
    assert dispatched[0][0] == enc_id and dispatched[0][2] == "RC-001"
    async_db.expire_all()
    enc = await async_db.get(Encounter, enc_id)
    e = _entry(enc)
    assert e.get("reconcile_attempts") == 2, (
        f"广播前必须预计数保 exhausted 可达，实际 {e}")
