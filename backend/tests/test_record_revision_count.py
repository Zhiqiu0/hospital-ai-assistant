# -*- coding: utf-8 -*-
"""打印件「经修订」标识的判据（2026-09-01 打印件实测发现）。

背景：打印件顶部那句「本文书经修订（…），修订留痕见医院审计日志」是**法定修订
标识**。此前判据是 `current_version > 1`——而正常签发流程本身就会产生 3 个版本：
    v1 ai_generated（AI 生成草稿）
    v2 doctor_edited（医生编辑）
    v3 doctor_signed（签发）
于是**每一份普通病历**都被印上「经修订（第 3 版）」。实测把一份从没被改过的病历
打出来，纸面上赫然写着"本文书经修订"。

后果不是不好看：标识因此完全失去意义——真正被管理员改过的病历反而无法与常规
病历区分，而病案室和法庭看到的是"所有病历都被修改过"。

真正的修订只有一条通道：管理员走 /admin/records/{id}/revise，产出
source='admin_revise' 的版本。本文件把这个判据钉住。
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.services.medical_record_service import MedicalRecordService


async def _mk_record(db, *, with_admin_revise: int = 0) -> tuple[str, str]:
    """建一份走完整签发流程的病历：AI 生成 → 医生编辑 → 签发（3 个版本）。"""
    patient = Patient(name="打印测试", gender="male")
    db.add(patient)
    await db.flush()
    enc = Encounter(patient_id=patient.id, doctor_id="doc-1",
                    visit_type="outpatient", visited_at=datetime.now())
    db.add(enc)
    await db.flush()
    rec = MedicalRecord(encounter_id=enc.id, record_type="outpatient",
                        status="submitted", current_version=3, record_no=1,
                        submitted_at=datetime.now())
    db.add(rec)
    await db.flush()
    for no, src in [(1, "ai_generated"), (2, "doctor_edited"), (3, "doctor_signed")]:
        db.add(RecordVersion(medical_record_id=rec.id, version_no=no,
                             content={"text": "正文"}, source=src))
    for i in range(with_admin_revise):
        db.add(RecordVersion(medical_record_id=rec.id, version_no=4 + i,
                             content={"text": "修订后正文"}, source="admin_revise"))
    if with_admin_revise:
        rec.current_version = 3 + with_admin_revise
    await db.commit()
    return patient.id, rec.id


@pytest.mark.asyncio
async def test_正常签发的病历不算修订(async_db):
    """三个版本是签发流程的正常产物，不是修订——这正是实测中印错的那一份。"""
    patient_id, _ = await _mk_record(async_db)
    res = await MedicalRecordService(async_db).list_by_patient(patient_id)
    item = res["items"][0] if isinstance(res, dict) else res[0]
    assert item["revision_count"] == 0, "从没改过的病历被判为「经修订」"


@pytest.mark.asyncio
async def test_管理员修订才计入(async_db):
    patient_id, _ = await _mk_record(async_db, with_admin_revise=2)
    res = await MedicalRecordService(async_db).list_by_patient(patient_id)
    item = res["items"][0] if isinstance(res, dict) else res[0]
    assert item["revision_count"] == 2


@pytest.mark.asyncio
async def test_修订次数不等于当前版本号(async_db):
    """两者必须解耦：version 会随签发流程涨，修订次数只随管理员改动涨。"""
    patient_id, _ = await _mk_record(async_db, with_admin_revise=1)
    res = await MedicalRecordService(async_db).list_by_patient(patient_id)
    item = res["items"][0] if isinstance(res, dict) else res[0]
    assert item["revision_count"] == 1
    assert item["revision_count"] != 4, "又把版本号当成修订次数了"
