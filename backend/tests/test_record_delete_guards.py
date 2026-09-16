# -*- coding: utf-8 -*-
"""空白草稿删除端点的守卫回归锁（2026-09-16 覆盖率盲区 #3）。

背景：DELETE /medical-records/{id} 是全系统唯一能物理删除病历行的口子，
承载"病历是法律文件、只能修订不能删"的最后防线，此前**零测试覆盖**——
四道守卫（已签发 409 / 有正文 409 / 有质控证据 409 / 外键解链后删）逻辑
复杂，恰是最容易改坏又最不能改坏的地方。
"""
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.medical_record import AITask, MedicalRecord, QCReport, RecordVersion
from app.models.patient import Patient
from app.models.user import User


def _doctor(uid="doc-1"):
    return User(id=uid, username=f"u_{uid}", password_hash="x",
                real_name="删测医生", role="doctor", is_active=True)


async def _mk_record(db, *, status="editing", text="", doctor_id="doc-1"):
    p = Patient(name="删测", gender="male")
    db.add(p)
    await db.flush()
    enc = Encounter(patient_id=p.id, doctor_id=doctor_id, visit_type="outpatient",
                    visited_at=datetime.now())
    db.add(enc)
    await db.flush()
    rec = MedicalRecord(encounter_id=enc.id, record_type="outpatient",
                        status=status, current_version=1, record_no=1)
    db.add(rec)
    await db.flush()
    db.add(RecordVersion(medical_record_id=rec.id, version_no=1,
                         content={"text": text}, source="manual"))
    await db.commit()
    return rec.id


async def _delete(async_db, record_id, user):
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            return await ac.delete(f"/api/v1/medical-records/{record_id}")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_已签发病历不可删除(async_db):
    rid = await _mk_record(async_db, status="submitted", text="正式内容")
    r = await _delete(async_db, rid, _doctor())
    assert r.status_code == 409 and "已签发" in r.json()["detail"]
    assert await async_db.get(MedicalRecord, rid) is not None, "行必须原样保留"


@pytest.mark.asyncio
async def test_有正文的草稿不可删除(async_db):
    rid = await _mk_record(async_db, status="editing", text="医生写了半页")
    r = await _delete(async_db, rid, _doctor())
    assert r.status_code == 409 and "已有内容" in r.json()["detail"]


@pytest.mark.asyncio
async def test_有质控证据的空白文书不可删除(async_db):
    rid = await _mk_record(async_db, text="")
    rec = await async_db.get(MedicalRecord, rid)
    async_db.add(QCReport(encounter_id=rec.encounter_id, medical_record_id=rid,
                          record_type="outpatient", rubric_key="zj_outpatient_emergency_2023",
                          score=100, grade="合格", passed=True, deductions=[]))
    await async_db.commit()
    r = await _delete(async_db, rid, _doctor())
    assert r.status_code == 409 and "质控" in r.json()["detail"]


@pytest.mark.asyncio
async def test_空白草稿删除成功且日志引用解链(async_db):
    rid = await _mk_record(async_db, text="")
    rec = await async_db.get(MedicalRecord, rid)
    task = AITask(task_type="qc", status="failed", encounter_id=rec.encounter_id,
                  medical_record_id=rid)
    async_db.add(task)
    await async_db.commit()
    task_id = task.id

    r = await _delete(async_db, rid, _doctor())
    assert r.status_code == 204
    assert await async_db.get(MedicalRecord, rid) is None
    # 日志型引用被置空而不是级联删（审计痕迹要留）
    async_db.expire_all()
    kept = await async_db.get(AITask, task_id)
    assert kept is not None and kept.medical_record_id is None


@pytest.mark.asyncio
async def test_他人接诊的文书不可删(async_db):
    rid = await _mk_record(async_db, text="", doctor_id="doc-1")
    r = await _delete(async_db, rid, _doctor(uid="doc-2"))
    assert r.status_code in (403, 404), f"越权删除未被拦：{r.status_code}"
