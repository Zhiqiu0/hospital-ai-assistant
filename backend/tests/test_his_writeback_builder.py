"""HIS 响应信封 / 接诊推送模型 / 回写组装 单测。"""
from datetime import date

import pytest

from app.his_adapter.models import ApiEnvelope, ok, err, AdmitPushRequest
from app.his_adapter.writeback_builder import build_writeback_payload
from app.models.patient import Patient
from app.models.encounter import Encounter, InquiryInput


def test_envelope_ok_and_err():
    e = ok({"patient_id": "p1"}, trace_id="t1")
    assert e.code == 0 and e.message == "success" and e.data == {"patient_id": "p1"} and e.trace_id == "t1"
    e2 = err(40001, "签名校验失败")
    assert e2.code == 40001 and e2.message == "签名校验失败" and e2.data == {}


def test_admit_request_minimal_required():
    """visit_id/hospital_code/patient_name 必填，其余可空（容错向后兼容）。"""
    req = AdmitPushRequest.model_validate(
        {"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"}
    )
    assert req.visit_id == "V1" and req.gender == "unknown" and req.doctor_code is None


@pytest.mark.asyncio
async def test_build_writeback_payload(async_db):
    p = Patient(name="李四", birth_date=date(1990, 5, 1))
    async_db.add(p)
    await async_db.commit()
    enc = Encounter(
        patient_id=p.id, doctor_id="doc-1", visit_type="outpatient",
        visit_no="V20260518001", status="in_progress",
        his_external_ref={"his_brand": "jinsuanpan", "hospital_code": "H1",
                          "his_patient_no": "PNO1", "his_visit_no": "V20260518001",
                          "his_doctor_no": "D001"},
    )
    async_db.add(enc)
    await async_db.commit()
    inq = InquiryInput(
        encounter_id=enc.id, version=1,
        chief_complaint="咳嗽3天", history_present_illness="受凉后咳嗽……",
        temperature="38.5", bp_systolic="120", bp_diastolic="80",
        western_diagnosis="急性支气管炎", tongue_coating="舌红苔黄",
    )
    async_db.add(inq)
    await async_db.commit()

    payload = await build_writeback_payload(async_db, enc.id, app_version="1.0.0")

    assert payload["visit_id"] == "V20260518001"
    assert payload["record_type"] == "outpatient"
    assert payload["is_tcm"] is True
    assert payload["status"] == "draft"
    assert payload["record"]["chief_complaint"] == "咳嗽3天"
    assert "history_informant" not in payload["record"]
    assert payload["vitals"] == {"temperature": "38.5", "bp_systolic": "120", "bp_diastolic": "80"}
    assert payload["diagnoses"] == [
        {"name": "急性支气管炎", "is_primary": True, "category": "western"}
    ]
    assert payload["meta"]["source"] == "mediscribe_ai"
    assert payload["meta"]["doctor_code"] == "D001"


@pytest.mark.asyncio
async def test_build_writeback_payload_emergency(async_db):
    """visit_type=emergency → record_type=emergency。"""
    p = Patient(name="王五", birth_date=date(1985, 1, 1))
    async_db.add(p)
    await async_db.commit()
    enc = Encounter(
        patient_id=p.id, doctor_id="doc-1", visit_type="emergency",
        visit_no="E1", status="in_progress",
        his_external_ref={"hospital_code": "H1", "his_patient_no": "P2", "his_visit_no": "E1"},
    )
    async_db.add(enc)
    await async_db.commit()
    payload = await build_writeback_payload(async_db, enc.id)
    assert payload["record_type"] == "emergency"
