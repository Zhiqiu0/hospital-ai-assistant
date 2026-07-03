"""一键同步上次病历（get_previous_record）单测。"""
from datetime import date

import pytest

from app.models.patient import Patient
from app.models.encounter import Encounter, InquiryInput
from app.services.encounter_service import EncounterService


@pytest.mark.asyncio
async def test_previous_record_copies_text_not_vitals(async_db):
    """带回上次的文字病历，体征数值绝不带回（本次需重测）。"""
    p = Patient(name="慢病张", birth_date=date(1960, 1, 1))
    async_db.add(p)
    await async_db.commit()

    prev = Encounter(patient_id=p.id, doctor_id="d1", visit_type="outpatient", status="completed")
    async_db.add(prev)
    await async_db.commit()
    async_db.add(InquiryInput(
        encounter_id=prev.id, version=1,
        chief_complaint="高血压复诊", history_present_illness="血压控制尚可",
        past_history="高血压10年", western_diagnosis="原发性高血压",
        treatment_plan="继续口服降压药", tongue_coating="舌淡红",
        temperature="36.5", bp_systolic="140", bp_diastolic="90", pulse="78",
    ))
    await async_db.commit()

    cur = Encounter(patient_id=p.id, doctor_id="d1", visit_type="outpatient", status="in_progress")
    async_db.add(cur)
    await async_db.commit()

    result = await EncounterService(async_db).get_previous_record(cur.id)

    assert result["source_encounter_id"] == prev.id
    f = result["fields"]
    # 文字病历带回
    assert f["chief_complaint"] == "高血压复诊"
    assert f["western_diagnosis"] == "原发性高血压"
    assert f["treatment_plan"] == "继续口服降压药"
    assert f["tongue_coating"] == "舌淡红"
    # 体征数值绝不带回
    for vital in ("temperature", "bp_systolic", "bp_diastolic", "pulse"):
        assert vital not in f
    # 空字段不带回
    assert "menstrual_history" not in f


@pytest.mark.asyncio
async def test_previous_record_empty_when_no_history(async_db):
    """初诊病人没有历史病历 → 返回空。"""
    p = Patient(name="初诊李", birth_date=date(1990, 1, 1))
    async_db.add(p)
    await async_db.commit()
    cur = Encounter(patient_id=p.id, doctor_id="d1", visit_type="outpatient", status="in_progress")
    async_db.add(cur)
    await async_db.commit()

    result = await EncounterService(async_db).get_previous_record(cur.id)
    assert result["source_encounter_id"] is None
    assert result["fields"] == {}
