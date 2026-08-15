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
    picked = (await db.execute(
        select(RecordVersion, MedicalRecord)
        .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
        .where(
            MedicalRecord.encounter_id == encounter_id,
            RecordVersion.version_no == MedicalRecord.current_version,
        )
        # 优先取「已签发」的那份（2026-08-13 第五轮审计修复）：
        # 原先只按 updated_at 倒序取最近更新的一份。住院一次接诊有入院记录/病程/
        # 出院小结等多份病历，医生刚签发出院小结、随后又碰了一下病程草稿，
        # 回写就会把那份草稿推给 HIS——回写的必须是刚签发的正式文书。
        .order_by(
            (MedicalRecord.status == "submitted").desc(),
            desc(MedicalRecord.submitted_at),
            desc(MedicalRecord.updated_at),
        )
        .limit(1)
    )).first()
    row, record_row = (picked[0], picked[1]) if picked else (None, None)
    full_text = _parse_record_text(row.content) if row else ""

    his_ref = encounter.his_external_ref or {}
    visit_id = his_ref.get("his_visit_no") or encounter.visit_no or ""
    # 回写的 record_type 取**病历自己的类型**（2026-08-13 第五轮审计修复）：
    # 原先只按接诊 visit_type 三分，住院会落进 else 被当成 outpatient 推给 HIS——
    # 而规范里住院有 admission_note / course_record / discharge_record / op_record
    # 等专属类型，推错类型 HIS 侧会归档到错误的文书栏目。
    # 病历表上就存着真实类型，直接用它；查不到再按接诊类型兜底。
    record_type = (
        record_row.record_type
        if record_row is not None and record_row.record_type
        else ("emergency" if encounter.visit_type == "emergency" else "outpatient")
    )

    # ── record_no：住院多份同类型文书的区分键（2026-08-14 第八轮审计）──────────
    #
    # 接口规范 §2.5 白纸黑字：「回写以（visit_id + record_type + record_no）为
    # 幂等键——该键对应的文书在 HIS 尚无则新建，已有则覆盖更新」，§3.2 请求体
    # 也列了这个字段。第六轮的 i20260814recordno 迁移专门为此在我方库里加了
    # record_no 并让签发时正确递增（1..15），**但回写 payload 从头到尾没带上它**。
    # 后果：住院 15 份日常病程，每次回写的 (visit_id, record_type) 逐字相同，
    # HIS 按规范只能认定是同一份文书被反复覆盖——我方库里 15 份都在，
    # HIS 病案里只剩最后一天那份。而医院的**法定病案是 HIS 那一份**。
    # 门急诊各只有一份，规范允许 record_no 可空，故仅在有值时下发。
    # 转字符串下发（2026-08-14 规范一致性核对修复）：规范 3.2 把 record_no 声明为
    # string，而这里原样下发 Python int → JSON number。厂商用强类型 DTO
    # （Java / C# 严格模式）反序列化会直接抛类型错误整包拒收；而它是幂等键的
    # 一段，类型不一致直接影响病案是新建还是覆盖，不能靠对方宽松解析碰运气。
    # 规范里 visit_id / vitals.* 一律是 string，这里跟着统一。
    _no = getattr(record_row, "record_no", None) if record_row is not None else None
    record_no = str(_no) if _no is not None else None

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
        # 幂等键第三段（见上方 record_no 说明）。
        "is_tcm": is_tcm,
        "status": "draft",
        "record": record,
        "vitals": vitals,
        "diagnoses": diagnoses,

        "meta": {
            "source": "mediscribe_ai",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            # 接诊推送落的 doctor_code（2026-08-11 联动后唯一来源；
            # 旧 embed 会话的 his_doctor_no 兜底已随 embed 下线删除，无存量数据）
            "doctor_code": his_ref.get("doctor_code") or "",
            "app_version": app_version,
        },
    }
    # ── 空值一律不下发（2026-08-14 规范一致性核对修复）────────────────────
    #
    # 规范 2.5 白纸黑字：「字段缺省（不传）= 不更新该项；传空串("") = 清空该项」。
    # 而原先 full_text 取不到正文时会发空串、record_no 无值时发 JSON null、
    # meta.doctor_code 取不到时发空串——按规范语义，厂商合规实现就会把 HIS 里
    # 已有的病历全文/医生工号**清掉**，而这恰恰是「取不到值」的异常路径，
    # 本该是「什么都别动」。record.* / vitals.* 走的就是「空则不下发」，
    # 唯独这几个破了规则，两处语义自相矛盾。
    # JSON null 更是规范里没定义的第三态（厂商可能当 "null" 字符串、当 0、或 NPE）。
    if record_no is not None:
        payload["record_no"] = record_no
    if full_text:
        payload["full_text"] = full_text
    if not payload["meta"].get("doctor_code"):
        payload["meta"].pop("doctor_code", None)

    return payload
