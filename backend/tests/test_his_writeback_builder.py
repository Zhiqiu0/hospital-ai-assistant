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
                          "doctor_code": "D001"},
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


# ── 第五轮审计修复的回归锁（2026-08-13）────────────────────────────────────
@pytest.mark.asyncio
async def test_inpatient_writeback_uses_real_record_type(async_db):
    """住院回写用病历自己的类型，且取已签发那份而非最近更新的草稿。

    原先 record_type 只按接诊 visit_type 三分，住院落进 else 被当成 outpatient
    推给 HIS，而规范里住院有 admission_note/course_record/discharge_record 等
    专属类型，推错 HIS 侧会归档到错误的文书栏目。
    取病历也只按 updated_at 倒序，医生刚签发出院小结、随后碰了下病程草稿，
    回写就会把草稿推过去——回写的必须是刚签发的正式文书。
    """
    from datetime import datetime

    from app.models.medical_record import MedicalRecord, RecordVersion

    p = Patient(name="住院患者", birth_date=date(1980, 1, 1))
    async_db.add(p)
    await async_db.commit()
    enc = Encounter(
        patient_id=p.id, doctor_id="doc-1", visit_type="inpatient",
        visit_no="V20260813IN", status="in_progress",
        his_external_ref={"his_visit_no": "V20260813IN", "doctor_code": "D001"},
    )
    async_db.add(enc)
    await async_db.commit()

    # 已签发的出院小结（早一点更新）
    signed = MedicalRecord(encounter_id=enc.id, record_type="discharge_record",
                           status="submitted", current_version=1,
                           submitted_at=datetime(2026, 8, 13, 10, 0, 0))
    async_db.add(signed)
    await async_db.flush()
    async_db.add(RecordVersion(medical_record_id=signed.id, version_no=1,
                               content={"text": "出院小结正文"}, source="doctor_signed"))

    # 之后又被碰过的病程草稿（updated_at 更晚）
    draft = MedicalRecord(encounter_id=enc.id, record_type="course_record",
                          status="draft", current_version=1)
    async_db.add(draft)
    await async_db.flush()
    async_db.add(RecordVersion(medical_record_id=draft.id, version_no=1,
                               content={"text": "病程草稿"}, source="doctor_edited"))
    await async_db.commit()

    payload = await build_writeback_payload(async_db, enc.id, app_version="1.0.0")

    assert payload["record_type"] == "discharge_record", (
        f"住院回写类型错了：{payload['record_type']}（原缺陷会是 outpatient）"
    )
    assert "出院小结正文" in (payload.get("full_text") or ""), "回写取到了草稿而不是已签发文书"
