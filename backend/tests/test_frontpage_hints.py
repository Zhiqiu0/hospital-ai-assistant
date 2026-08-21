# -*- coding: utf-8 -*-
"""出院诊断完整性交叉提示测试（2026-08-21 阶段3，提示级不扣分）。"""
from datetime import date, datetime

import pytest

from app.models.encounter import Encounter
from app.models.patient import Patient
from app.services.ai._qc_frontpage import check_diagnosis_hints, load_front_page
from app.services.medical_record_service import MedicalRecordService


async def _seed(db):
    db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1),
                   id_card="110101197001011959", blood_type="A"))
    db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-1", visit_type="inpatient",
        status="in_progress", visited_at=datetime(2026, 8, 1), admission_route="门诊",
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_hint_lists_diagnoses_seen_in_signed_records(async_db):
    """已签发文书诊断章节出现过、当前条目缺失 → 提示（不扣分）。"""
    await _seed(async_db)
    svc = MedicalRecordService(async_db)
    await svc.quick_save(
        encounter_id="enc-1", record_type="admission_note", doctor_id="doc-1",
        content="【主诉】\n头晕\n\n【入院诊断】\n中医诊断：眩晕病 — 肝阳上亢证\n西医诊断：1.高血压病；2.2型糖尿病",
    )
    hints = await check_diagnosis_hints(
        async_db, "enc-1", "discharge_record",
        current_diagnoses=({"name": "高血压病"}, {"name": "眩晕病"}),
    )
    assert len(hints) == 1
    desc = hints[0]["issue_description"]
    assert "2型糖尿病" in desc, "漏掉的合并症必须点名"
    assert "高血压病" not in desc.split("：")[1].split("。")[0].replace("2型糖尿病", ""), \
        "已包含的诊断不该出现在缺失列表"
    assert hints[0]["score_impact"] == "提示", "交叉检查是提示级，绝不扣分"


@pytest.mark.asyncio
async def test_hint_silent_when_complete_or_not_discharge(async_db):
    """条目齐全不提示；非出院记录不提示。"""
    await _seed(async_db)
    svc = MedicalRecordService(async_db)
    await svc.quick_save(
        encounter_id="enc-1", record_type="admission_note", doctor_id="doc-1",
        content="【入院诊断】\n西医诊断：高血压病",
    )
    assert await check_diagnosis_hints(
        async_db, "enc-1", "discharge_record", ({"name": "高血压病"},)
    ) == []
    assert await check_diagnosis_hints(
        async_db, "enc-1", "course_record", ({"name": "别的"},)
    ) == []


@pytest.mark.asyncio
async def test_load_front_page_assembles_all_sources(async_db):
    """预取聚合：患者档案 + 接诊 + 诊断条目 → loaded=True。"""
    await _seed(async_db)
    from app.schemas.diagnosis import DiagnosisItemIn
    from app.services.diagnosis_service import DiagnosisService
    await DiagnosisService(async_db).replace_all("enc-1", [
        DiagnosisItemIn(category="western", name="高血压病", is_primary=True,
                        admission_condition="有"),
    ])
    fp = await load_front_page(async_db, "enc-1")
    assert fp.loaded and fp.id_card == "110101197001011959"
    assert fp.admission_route == "门诊" and fp.blood_type == "A"
    assert fp.diagnoses[0]["name"] == "高血压病" and fp.diagnoses[0]["is_primary"]
    # 无 encounter → 未加载态（规则全跳过）
    assert (await load_front_page(async_db, None)).loaded is False
