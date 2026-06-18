"""把一次接诊的病历组装成 HIS 回写 payload。

数据来源：
  - Encounter.his_external_ref / visit_no / visit_type → 关联键、病历类型
  - 最新 InquiryInput（分字段）→ record.* / vitals.* / diagnoses[]
  - 最新 RecordVersion.content → full_text（整段签发全文）

红线：体征为医生录入的真实值（InquiryInput 字段），AI 不编造；空字段不下发。
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion

# record.* 结构化字段（门诊/急诊用；住院专属字段后续向后兼容追加）
_RECORD_FIELDS = [
    "chief_complaint", "onset_time", "history_present_illness", "past_history",
    "allergy_history", "personal_history", "current_medications", "history_informant",
    "family_history", "marital_history", "menstrual_history", "physical_exam",
    "auxiliary_exam", "tcm_inspection", "tcm_auscultation", "tongue_coating",
    "pulse_condition", "treatment_method", "treatment_plan", "followup_advice",
    "precautions", "observation_notes", "patient_disposition",
]
_VITALS_FIELDS = [
    "temperature", "pulse", "respiration", "bp_systolic", "bp_diastolic",
    "spo2", "height", "weight",
]


def _parse_record_text(content: Any) -> str:
    """RecordVersion.content → 全文（{"text":...} 取 text，纯字符串原样，其它空串）。"""
    if isinstance(content, dict):
        return content.get("text") or ""
    if isinstance(content, str):
        return content
    return ""


def _build_diagnoses(inq: Optional[InquiryInput]) -> list[dict]:
    """从三个诊断文本字段拼成 diagnoses[]；第一个非空诊断标主诊断。"""
    if inq is None:
        return []
    out: list[dict] = []
    if inq.western_diagnosis:
        out.append({"name": inq.western_diagnosis, "is_primary": True, "category": "western"})
    if inq.tcm_disease_diagnosis:
        out.append({"name": inq.tcm_disease_diagnosis, "is_primary": not out, "category": "tcm_disease"})
    if inq.tcm_syndrome_diagnosis:
        out.append({"name": inq.tcm_syndrome_diagnosis, "is_primary": not out, "category": "tcm_syndrome"})
    return out


async def build_writeback_payload(
    db: AsyncSession, encounter_id: str, app_version: str = "1.0.0"
) -> dict:
    """组装一次接诊的病历回写 payload（dict，结构见接口规范 3.2）。"""
    encounter = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise ValueError(f"encounter not found: {encounter_id}")

    # 最新问诊（分字段）
    inq = (await db.execute(
        select(InquiryInput)
        .where(InquiryInput.encounter_id == encounter_id)
        .order_by(desc(InquiryInput.updated_at))
        .limit(1)
    )).scalar_one_or_none()

    # 最新病历版本全文
    row = (await db.execute(
        select(RecordVersion)
        .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
        .where(
            MedicalRecord.encounter_id == encounter_id,
            RecordVersion.version_no == MedicalRecord.current_version,
        )
        .order_by(desc(MedicalRecord.updated_at))
        .limit(1)
    )).scalar_one_or_none()
    full_text = _parse_record_text(row.content) if row else ""

    his_ref = encounter.his_external_ref or {}
    visit_id = his_ref.get("his_visit_no") or encounter.visit_no or ""
    record_type = "emergency" if encounter.visit_type == "emergency" else "outpatient"

    record = {f: getattr(inq, f) for f in _RECORD_FIELDS if inq and getattr(inq, f, None)}
    vitals = {f: getattr(inq, f) for f in _VITALS_FIELDS if inq and getattr(inq, f, None)}
    diagnoses = _build_diagnoses(inq)
    is_tcm = bool(
        inq and (inq.tcm_disease_diagnosis or inq.tcm_syndrome_diagnosis
                 or inq.tongue_coating or inq.pulse_condition
                 or inq.tcm_inspection or inq.tcm_auscultation)
    )

    payload: dict = {
        "visit_id": visit_id,
        "record_type": record_type,
        "is_tcm": is_tcm,
        "status": "draft",
        "record": record,
        "vitals": vitals,
        "diagnoses": diagnoses,
        "full_text": full_text,
        "meta": {
            "source": "mediscribe_ai",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "doctor_code": his_ref.get("his_doctor_no") or "",
            "app_version": app_version,
        },
    }
    return payload
