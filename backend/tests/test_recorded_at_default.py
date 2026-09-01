# -*- coding: utf-8 -*-
"""病历必须有记录时间，否则补记判定整条空转（2026-09-02 住院支线实测发现）。

实测：生产库 46 份病历，recorded_at **全部为 NULL，一条都没有**。
而 record_time.is_late_entry() 第一行就是「recorded_at 为 None 直接 return False」
——也就是说 record_time.py 模块文档里写的「系统不阻止医生记录较早的诊疗时点，
但**一定把它标出来**」，从上线到今天一次都没有生效过。

根因：四个建 MedicalRecord 的地方只有 auto_save_draft 一处接收 recorded_at 参数，
另三处（save_ai_draft / quick_save / crud）压根不传；而前端新建病程时的注释明确
写着「不发 recorded_at：留服务器取 now」——**服务器那半从来没实现**。

修法是服务端兜底取 now：
  · 正常书写 → recorded_at ≈ created_at，差值~0，不判补记（不误伤）
  · 医生把记录时间改成更早的诊疗时点（补写昨天的查房）→ 超阈值才标补记
这样《病历书写基本规范》要求的补记标注才真正可用。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.services.medical_record_service import MedicalRecordService
from app.services.record_time import is_late_entry


async def _mk_inpatient(db) -> str:
    p = Patient(name="补记测试", gender="male")
    db.add(p)
    await db.flush()
    e = Encounter(patient_id=p.id, doctor_id="d1", visit_type="inpatient",
                  visited_at=datetime.now())
    db.add(e)
    await db.commit()
    return e.id


async def _fetch(db, enc_id: str) -> MedicalRecord:
    return (await db.execute(
        select(MedicalRecord).where(MedicalRecord.encounter_id == enc_id)
    )).scalars().first()


@pytest.mark.asyncio
async def test_草稿路径建的病历有记录时间(async_db):
    enc_id = await _mk_inpatient(async_db)
    await MedicalRecordService(async_db).auto_save_draft(
        encounter_id=enc_id, record_type="admission_note",
        content="入院记录", user_id="d1")
    rec = await _fetch(async_db, enc_id)
    assert rec.recorded_at is not None, "recorded_at 为空 → 补记判定永远返回 False"


@pytest.mark.asyncio
async def test_AI生成路径建的病历有记录时间(async_db):
    """这条此前完全不传 recorded_at——而住院文书多数是从 AI 生成落库的。"""
    enc_id = await _mk_inpatient(async_db)
    await MedicalRecordService(async_db).save_ai_draft(
        encounter_id=enc_id, record_type="course_record",
        content="病程记录", user_id="d1")
    rec = await _fetch(async_db, enc_id)
    assert rec.recorded_at is not None


@pytest.mark.asyncio
async def test_医生显式给的记录时间不被覆盖(async_db):
    """兜底只在缺省时生效；医生补写昨天的查房，那个时间必须原样保留。"""
    enc_id = await _mk_inpatient(async_db)
    yesterday = datetime.now() - timedelta(days=1)
    await MedicalRecordService(async_db).auto_save_draft(
        encounter_id=enc_id, record_type="course_record",
        content="补写昨天的查房", user_id="d1", recorded_at=yesterday)
    rec = await _fetch(async_db, enc_id)
    assert abs((rec.recorded_at - yesterday).total_seconds()) < 2


@pytest.mark.asyncio
async def test_正常书写不被误判为补记(async_db):
    """兜底取 now 之后，recorded_at≈created_at，差值远小于 12 小时阈值。"""
    enc_id = await _mk_inpatient(async_db)
    await MedicalRecordService(async_db).auto_save_draft(
        encounter_id=enc_id, record_type="admission_note",
        content="当场书写", user_id="d1")
    rec = await _fetch(async_db, enc_id)
    assert is_late_entry(rec.recorded_at, rec.created_at) is False


@pytest.mark.asyncio
async def test_补写昨天的查房被标为补记(async_db):
    """这正是 record_time 模块声称要做、而此前一次都没做成的事。"""
    enc_id = await _mk_inpatient(async_db)
    await MedicalRecordService(async_db).auto_save_draft(
        encounter_id=enc_id, record_type="course_record",
        content="补写昨天的查房", user_id="d1",
        recorded_at=datetime.now() - timedelta(days=1))
    rec = await _fetch(async_db, enc_id)
    assert is_late_entry(rec.recorded_at, rec.created_at) is True
