"""多行容错 + 取消接诊过滤 回归

两处历史坑：
  1. (encounter_id, record_type) / (encounter_id) 均无唯一约束，历史上可能存在多行
     （create() 无条件新建、并发首存各插一条）。quick_save / save_inquiry 若用
     scalar_one_or_none() 会抛 MultipleResultsFound → 500，导致病历永远签发不出去 /
     问诊永远存不上。修复：改 order_by + first() 取最新一条，与读侧一致。
  2. get_previous_record 之前不过滤 status，会把「已取消」接诊的问诊当复诊参考带回。
"""
from datetime import date, datetime

import pytest

from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.schemas.encounter import InquiryInputUpdate
from app.services.encounter_service import EncounterService
from app.services.medical_record_service import MedicalRecordService


@pytest.mark.asyncio
async def test_quick_save_tolerates_duplicate_records(async_db):
    """同接诊同类型存在两条病历时，签发不再抛 MultipleResultsFound。"""
    p = Patient(name="多行甲", birth_date=date(1970, 1, 1))
    async_db.add(p)
    await async_db.commit()
    enc = Encounter(patient_id=p.id, doctor_id="d1", visit_type="outpatient", status="in_progress")
    async_db.add(enc)
    await async_db.commit()
    # 故意造两条同 (encounter_id, record_type) 病历
    async_db.add_all([
        MedicalRecord(encounter_id=enc.id, record_type="outpatient"),
        MedicalRecord(encounter_id=enc.id, record_type="outpatient"),
    ])
    await async_db.commit()

    svc = MedicalRecordService(async_db)
    # 修复前这里会抛 MultipleResultsFound；修复后正常签发
    rec = await svc.quick_save(
        encounter_id=enc.id, record_type="outpatient", content="签发内容", doctor_id="d1",
    )
    assert rec.status == "submitted"


@pytest.mark.asyncio
async def test_save_inquiry_tolerates_duplicate_rows(async_db):
    """同接诊存在两条 InquiryInput 时，保存问诊不再抛 MultipleResultsFound。"""
    p = Patient(name="多行乙", birth_date=date(1970, 1, 1))
    async_db.add(p)
    await async_db.commit()
    enc = Encounter(patient_id=p.id, doctor_id="d1", visit_type="outpatient", status="in_progress")
    async_db.add(enc)
    await async_db.commit()
    async_db.add_all([
        InquiryInput(encounter_id=enc.id, version=1, chief_complaint="旧A"),
        InquiryInput(encounter_id=enc.id, version=1, chief_complaint="旧B"),
    ])
    await async_db.commit()

    svc = EncounterService(async_db)
    res = await svc.save_inquiry(enc.id, InquiryInputUpdate(chief_complaint="新主诉"))
    assert res["chief_complaint"] == "新主诉"


@pytest.mark.asyncio
async def test_previous_record_skips_cancelled_encounter(async_db):
    """上一次接诊若已取消，不能当复诊参考带回。"""
    p = Patient(name="取消丙", birth_date=date(1960, 1, 1))
    async_db.add(p)
    await async_db.commit()
    # 唯一的历史接诊是 cancelled
    cancelled = Encounter(patient_id=p.id, doctor_id="d1", visit_type="outpatient", status="cancelled")
    async_db.add(cancelled)
    await async_db.commit()
    async_db.add(InquiryInput(
        encounter_id=cancelled.id, version=1,
        chief_complaint="取消接诊的主诉", visit_time="2026-06-01 09:00",
    ))
    await async_db.commit()
    cur = Encounter(patient_id=p.id, doctor_id="d1", visit_type="outpatient", status="in_progress")
    async_db.add(cur)
    await async_db.commit()

    result = await EncounterService(async_db).get_previous_record(cur.id)
    # 取消接诊被排除 → 视为无历史
    assert result["source_encounter_id"] is None
    assert result["fields"] == {}
