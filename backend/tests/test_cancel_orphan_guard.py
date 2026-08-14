"""取消接诊时的孤儿档案判定（2026-08-14 第八轮审计 medium）。

原先「孤儿」只判「除本接诊外没有别的接诊」。可医生给新病人建档后，影像科
完全可能已经在这次接诊里传了一套 CT 并发布报告；医生发现信息录错点「取消接诊」，
档案就被软删了——而 imaging_studies 那行仍在、patient_id 指向一个查不到的患者、
影像科工作列表照样列出它、Orthanc 里带患者姓名的 DICOM 原样保留。
更糟的是已发布的 study 禁止删除（pacs_reports 有 409 守卫），
这套孤儿影像连影像科都清不掉。

而全仓没有任何一处把 is_deleted 写回 False，也没有「已删档案」列表或恢复入口
——误点一次就永久失联。
"""

from datetime import date, datetime

import pytest

from app.models.encounter import Encounter
from app.models.imaging import ImagingStudy
from app.models.patient import Patient
from app.models.user import User
from app.models.voice_record import VoiceRecord
from app.services.encounter_service import EncounterService


async def _seed(db):
    db.add(User(id="doc-1", username="d1", password_hash="x", real_name="医生",
                role="doctor", is_active=True))
    db.add(Patient(id="p1", name="王六", birth_date=date(1980, 1, 1)))
    db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-1",
        visit_type="outpatient", status="in_progress",
        visited_at=datetime(2026, 8, 1),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_名下有影像时不软删患者档案(async_db):
    await _seed(async_db)
    async_db.add(ImagingStudy(
        id="st-1", patient_id="p1", uploaded_by="doc-1",
        modality="CT", status="published",
    ))
    await async_db.commit()

    res = await EncounterService(async_db).cancel("enc-1", "doc-1", "录错了")

    assert res["patient_soft_deleted"] is False, "把还挂着影像的患者档案删了"
    patient = await async_db.get(Patient, "p1")
    assert patient.is_deleted is False


@pytest.mark.asyncio
async def test_名下有语音记录时不软删(async_db):
    await _seed(async_db)
    async_db.add(VoiceRecord(
        id="vr-1", encounter_id="enc-1", doctor_id="doc-1",
        visit_type="outpatient", raw_transcript="口述内容", status="transcribed",
    ))
    await async_db.commit()

    res = await EncounterService(async_db).cancel("enc-1", "doc-1", "录错了")
    assert res["patient_soft_deleted"] is False


@pytest.mark.asyncio
async def test_真正的空档案仍然会被软删(async_db):
    """防过度收紧：建完就取消、名下什么都没有的，仍该清掉，
    否则查重时会一直搜到一个"明明被取消的人"。"""
    await _seed(async_db)

    res = await EncounterService(async_db).cancel("enc-1", "doc-1", "点错了")

    assert res["patient_soft_deleted"] is True
    patient = await async_db.get(Patient, "p1")
    assert patient.is_deleted is True
