"""回写必须来自该签发版本的正文，不能复活可变问诊里的旧字段。"""
from datetime import datetime

import pytest

from app.his_adapter.writeback_builder import build_writeback_payload
from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.services.ai.record_renderer import render_record


async def _signed(db, text, record_type="outpatient"):
    """仅使用合成资料，造一个已签发版本及刻意不一致的旧问诊。"""
    db.add(Patient(id="projection-p", name="测试患者"))
    db.add(Encounter(id="projection-e", patient_id="projection-p", doctor_id="doc",
                     visit_type="outpatient", status="completed", visit_no="test"))
    db.add(InquiryInput(encounter_id="projection-e", chief_complaint="旧主诉",
                        treatment_plan="旧处置", temperature="39", western_diagnosis="旧诊断"))
    record = MedicalRecord(id="projection-r", encounter_id="projection-e",
                           record_type=record_type, status="submitted", current_version=1,
                           submitted_at=datetime(2026, 10, 12))
    version = RecordVersion(medical_record_id=record.id, version_no=1,
                            content={"text": text}, source="doctor_signed")
    db.add_all([record, version])
    await db.flush()
    return record, version


@pytest.mark.asyncio
async def test_writeback_uses_final_text_and_clears_removed_fields(async_db):
    """最终改写和删除均以正文为准；删除字段显式空串下发给HIS清空。"""
    text = render_record("outpatient", {"chief_complaint": "终稿主诉", "physical_exam_vitals": "T:36.5℃"})
    await _signed(async_db, text)
    payload = await build_writeback_payload(async_db, "projection-e")
    assert payload["record"]["chief_complaint"] == "终稿主诉"
    assert payload["record"]["treatment_plan"] == ""
    assert payload["vitals"]["temperature"] == "36.5"
    assert payload["vitals"] == {"temperature": "36.5"}, "规范体征特例：未测项必须缺省，不得清空HIS已有测量值"
    assert payload["diagnoses"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["任意自定义正文", "【主诉】\n头痛\n【主诉】\n胸痛", "【自定义栏目】\n正文"])
async def test_unknown_or_ambiguous_format_rejects_writeback(async_db, text):
    """未知和重复结构不能假装完成逐字段回填，更不能偷偷用旧问诊。"""
    await _signed(async_db, text)
    with pytest.raises(ValueError, match="回写"):
        await build_writeback_payload(async_db, "projection-e")


@pytest.mark.asyncio
async def test_projection_failure_replaces_previous_success_without_sending(async_db, monkeypatch):
    """格式错误必须落文书级error，刷新后不能仍显示上次成功，也不得调用外部通道。"""
    from app.his_adapter import writeback_sender
    await _signed(async_db, "未知自由正文")
    encounter = await async_db.get(Encounter, "projection-e")
    encounter.his_external_ref = {"writeback_records": {"outpatient:1": {"status": "success"},
                                                       "course_record:2": {"status": "success"}}}

    async def forbidden(*args, **kwargs):
        raise AssertionError("投影失败不得发送")

    monkeypatch.setattr(writeback_sender, "_send_payload", forbidden)
    result = await writeback_sender.send_writeback(async_db, encounter.id, record_id="projection-r")
    assert not result.ok and result.status == "error"
    assert encounter.his_external_ref["writeback_records"]["outpatient:1"]["status"] == "error"
    assert encounter.his_external_ref["writeback_records"]["course_record:2"]["status"] == "success"
    previous = dict(encounter.his_external_ref)
    result = await writeback_sender.send_writeback(async_db, encounter.id, record_id="missing")
    assert not result.ok
    assert encounter.his_external_ref == previous


@pytest.mark.parametrize("record_type", ["outpatient", "emergency", "admission_note", "first_course_record",
    "course_record", "senior_round", "discharge_record", "pre_op_summary", "op_record", "post_op_record"])
def test_all_standard_renderers_can_be_projected(record_type):
    """十类规范输出均可回写；已知全文专属字段不扩充厂商契约，也不误判非法。"""
    from app.his_adapter.record_projection import project_record
    from app.services.ai.record_schemas import get_schema
    data = {key: "测试内容" for key in get_schema(record_type)}
    data["physical_exam_vitals"] = "T:[未测] P:72次/分 BP:120/80mmHg"
    text = render_record(record_type, data, patient_gender="女")
    projection = project_record(record_type, text)
    assert projection["record_type"] == record_type


@pytest.mark.asyncio
async def test_frozen_coding_and_vitals_survive_later_encounter_changes(async_db):
    """冻结后重推不读取新诊断/新体征，版本投影篡改会使签名失效。"""
    from app.his_adapter.record_projection import freeze_record_projection
    from app.models.encounter import Diagnosis
    from app.services._record_signature import compute_sign_hash, verify_version_against
    text = render_record("outpatient", {"western_diagnosis": "高血压病", "physical_exam_vitals": "T:36.5℃"})
    record, version = await _signed(async_db, text)
    diagnosis = Diagnosis(encounter_id="projection-e", category="western", name="高血压病", code="I10", code_type="ICD10", is_primary=True)
    async_db.add(diagnosis)
    await async_db.flush()
    projection = await freeze_record_projection(async_db, "projection-e", "outpatient", text)
    version.content = {"text": text, "his_projection": projection}
    version.sign_hash = compute_sign_hash(content_text=text, patient_snapshot=None, doctor_id="",
        submitted_at_iso=record.submitted_at.isoformat(), prev_hash="0" * 64, his_projection=projection)
    assert verify_version_against(version, record)
    diagnosis.code = "CHANGED"
    diagnosis.name = "新诊断"
    payload = await build_writeback_payload(async_db, "projection-e")
    assert payload["diagnoses"][0]["code"] == "I10"
    assert payload["vitals"]["temperature"] == "36.5"
    projection["vitals"]["temperature"] = "99"
    assert not verify_version_against(version, record)


def test_legacy_signature_algorithm_is_unchanged():
    """旧版本无投影时仍使用原序列化输入，不能使历史签名全部失效。"""
    import hashlib
    import json
    from app.services._record_signature import compute_sign_hash
    original = {"content": "旧正文", "snapshot": {}, "doctor_id": "d", "submitted_at": "t", "prev_hash": "p"}
    expected = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert compute_sign_hash(content_text="旧正文", patient_snapshot={}, doctor_id="d", submitted_at_iso="t", prev_hash="p") == expected


@pytest.mark.asyncio
async def test_changed_primary_name_is_not_guessed_or_given_old_code(async_db):
    """正文改名后无法确认原主诊断，冻结为明确失败，不能猜第一项或移植旧编码。"""
    from app.his_adapter.record_projection import freeze_record_projection
    text = render_record("outpatient", {"western_diagnosis": "新名称"})
    await _signed(async_db, text)
    previous = {"diagnoses": [{"name": "旧名称", "category": "western", "code": "OLD", "is_primary": True}]}
    result = await freeze_record_projection(async_db, "projection-e", "outpatient", text, previous_projection=previous)
    assert "主诊断" in result.get("error", "")
    assert "diagnoses" not in result, "失败候选仅作冻结依据，不得冒充可发送的诊断数组"


@pytest.mark.asyncio
async def test_legacy_diagnosis_without_frozen_primary_is_explicit_failure(async_db):
    """旧版只有正文没有主诊断快照，不得用今天的主诊断伪装历史选择。"""
    await _signed(async_db, render_record("outpatient", {"western_diagnosis": "高血压病"}))
    with pytest.raises(ValueError, match="主诊断"):
        await build_writeback_payload(async_db, "projection-e")


def test_alias_sections_cannot_overwrite_same_field():
    """同义标题不能覆盖同一个厂商字段，避免把一段医生正文悄悄丢掉。"""
    from app.his_adapter.record_projection import project_record
    with pytest.raises(ValueError, match="重复"):
        project_record("admission_note", "【辅助检查】\n甲\n【辅助检查（入院前）】\n乙")


def test_inline_second_diagnosis_label_is_not_part_of_name():
    """第二个类别标签未分隔时必须报歧义，不能把中医标签并入西医名称。"""
    from app.his_adapter.record_projection import project_record
    with pytest.raises(ValueError, match="诊断"):
        project_record("emergency", "【诊断】\n西医诊断：甲 中医诊断：乙")


def test_assessment_and_standalone_medication_cannot_overwrite():
    """专项评估和独立用药节都投影同字段时必须拒绝覆盖。"""
    from app.his_adapter.record_projection import project_record
    with pytest.raises(ValueError, match="重复"):
        project_record("admission_note", "【当前用药】\n甲\n【专项评估】\n· 当前用药：乙")


@pytest.mark.asyncio
async def test_format_error_preserves_signed_diagnosis_basis_for_repair(async_db):
    """格式修好且诊断未改名时，可使用当时冻结的明确选择恢复回写，不读今天条目。"""
    from app.his_adapter.record_projection import freeze_record_projection
    from app.models.encounter import Diagnosis
    await _signed(async_db, "自由正文")
    diagnosis = Diagnosis(encounter_id="projection-e", name="高血压病", category="western", code="I10", code_type="ICD10", is_primary=True)
    async_db.add(diagnosis)
    failed = await freeze_record_projection(async_db, "projection-e", "outpatient", "自由正文")
    assert "error" in failed and "diagnoses" not in failed
    diagnosis.code = "CHANGED"
    diagnosis.name = "后来诊断"
    await async_db.flush()
    fixed = await freeze_record_projection(async_db, "projection-e", "outpatient",
        render_record("outpatient", {"western_diagnosis": "高血压病"}), previous_projection=failed)
    assert "error" not in fixed
    assert fixed["diagnoses"][0]["code"] == "I10"
    assert fixed["diagnoses"][0]["is_primary"] is True
