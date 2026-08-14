"""管理员修订病历后必须重推 HIS（2026-08-14 第八轮审计 high）。

原先 revise_record 完全不碰回写：门诊病历签发 → 自动回写 HIS 成功 → 事后发现
诊断录错 → 管理员在后台修订、填理由、系统建新版本进签名链、前端提示修订成功；
而 **HIS 病案里躺着的仍是修订前的错误版本，永久不会更新**，医生和管理员都以为
改过了。对账任务也够不着——它只捞 status 属 {skipped, write_failed,
refresh_failed, error} 或从未回写的，'success' 不在重投集合里。

而修订的动机通常正是「原版本有错」——这恰恰最不能让 HIS 停在旧版本。
"""

from datetime import date, datetime

import pytest

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import User
from app.services.admin_record_service import AdminRecordService


async def _seed(db, *, his: bool):
    db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    db.add(User(id="admin-1", username="admin", password_hash="x",
                real_name="管理员", role="admin", is_active=True))
    db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-1",
        visit_type="outpatient", status="completed",
        visited_at=datetime(2026, 8, 1), visit_no="MZ001",
        his_external_ref=(
            {"source": "admit_push", "his_visit_no": "MZ001",
             "writeback": {"status": "success"}} if his else None
        ),
    ))
    rec = MedicalRecord(id="rec-1", encounter_id="enc-1", record_type="outpatient",
                        record_no=1, status="submitted", current_version=1,
                        submitted_at=datetime(2026, 8, 1, 10, 0))
    db.add(rec)
    await db.flush()
    db.add(RecordVersion(id="v1", medical_record_id="rec-1", version_no=1,
                         content={"text": "诊断：胃炎"}, source="doctor_signed",
                         triggered_by="doc-1"))
    await db.flush()


@pytest.mark.asyncio
async def test_修订his来源病历会派发重推(async_db, monkeypatch):
    from app.config import settings
    import app.his_adapter.bg_tasks as bg

    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    spawned: list[str] = []
    monkeypatch.setattr(bg, "spawn", lambda coro, name=None: (coro.close(), spawned.append(name))[1])

    await _seed(async_db, his=True)
    admin = (await async_db.get(User, "admin-1"))

    res = await AdminRecordService(async_db).revise_record(
        "rec-1", "诊断：胃溃疡", "诊断录错，更正", admin
    )

    assert res["his_writeback"] == "dispatched", "修订后没有重推 HIS，病案永久停在错误版本"
    assert any("writeback-revise" in (n or "") for n in spawned)


@pytest.mark.asyncio
async def test_非his来源病历修订不派发(async_db, monkeypatch):
    """普通 SaaS 接诊没有 HIS 上下文，不该凭空派发。"""
    from app.config import settings
    import app.his_adapter.bg_tasks as bg

    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    spawned: list[str] = []
    monkeypatch.setattr(bg, "spawn", lambda coro, name=None: (coro.close(), spawned.append(name))[1])

    await _seed(async_db, his=False)
    admin = (await async_db.get(User, "admin-1"))

    res = await AdminRecordService(async_db).revise_record(
        "rec-1", "改一下", "笔误", admin
    )

    assert res["his_writeback"] is None
    assert spawned == []


@pytest.mark.asyncio
async def test_保险丝关闭时不派发(async_db, monkeypatch):
    from app.config import settings
    import app.his_adapter.bg_tasks as bg

    monkeypatch.setattr(settings, "his_adapter_enabled", False)
    spawned: list[str] = []
    monkeypatch.setattr(bg, "spawn", lambda coro, name=None: (coro.close(), spawned.append(name))[1])

    await _seed(async_db, his=True)
    admin = (await async_db.get(User, "admin-1"))

    res = await AdminRecordService(async_db).revise_record("rec-1", "改", "理由", admin)
    assert res["his_writeback"] is None
