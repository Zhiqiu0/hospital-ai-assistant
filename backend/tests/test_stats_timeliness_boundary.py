# -*- coding: utf-8 -*-
"""时效达标率的边界判定（2026-09-02 统计口径对拍）。

这些数字医务科要拿去考核医生——月度通报上写着某位医生入院记录达标率 80%，
就得经得起他拿病历来对。生产上手工按规范算与系统算完全一致，但样本各只有
1 份、且都达标，说明不了判据在边界上对不对。本文件补边界样本。

法定时限（record_deadlines.RECORD_DEADLINES 是唯一真相源）：
  入院记录 24h（自入院）／首次病程 8h（自入院）／出院记录 24h（自**出院**）
"""
from datetime import datetime, timedelta

import pytest

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.services.admin_stats_service import get_quality_health


async def _mk(db, *, record_type: str, hours_after_start: float,
              discharged: bool = False) -> None:
    """造一份「距起算点 N 小时才签发」的已签发文书。"""
    p = Patient(name="时效样本", gender="male")
    db.add(p)
    await db.flush()
    admitted = datetime.now() - timedelta(days=2)
    enc = Encounter(patient_id=p.id, doctor_id="doc-1", visit_type="inpatient",
                    visited_at=admitted,
                    completed_at=admitted + timedelta(hours=12) if discharged else None)
    db.add(enc)
    await db.flush()
    start = enc.completed_at if discharged else enc.visited_at
    db.add(MedicalRecord(
        encounter_id=enc.id, record_type=record_type, status="submitted",
        current_version=1, record_no=1,
        submitted_at=start + timedelta(hours=hours_after_start)))
    await db.commit()


async def _rate(db, rtype: str) -> dict:
    return (await get_quality_health(db, days=30))["timeliness"].get(rtype, {})


@pytest.mark.asyncio
async def test_入院记录24小时边界(async_db):
    await _mk(async_db, record_type="admission_note", hours_after_start=23.9)
    await _mk(async_db, record_type="admission_note", hours_after_start=24.1)
    r = await _rate(async_db, "admission_note")
    assert r["total"] == 2 and r["on_time"] == 1, f"边界判错：{r}"
    assert r["limit_hours"] == 24


@pytest.mark.asyncio
async def test_首次病程8小时边界(async_db):
    """首程 8 小时是住院里最容易超的一条，也是质控通报最常点名的。"""
    await _mk(async_db, record_type="first_course_record", hours_after_start=7.5)
    await _mk(async_db, record_type="first_course_record", hours_after_start=8.5)
    r = await _rate(async_db, "first_course_record")
    assert r["total"] == 2 and r["on_time"] == 1, f"边界判错：{r}"


@pytest.mark.asyncio
async def test_出院记录从出院时刻起算而不是入院(async_db):
    """住半个月的病人，出院记录若从**入院**起算必然超时——那样每一份出院记录
    都不达标，指标直接失去意义。起算点必须是出院时刻。"""
    await _mk(async_db, record_type="discharge_record", hours_after_start=20,
              discharged=True)
    r = await _rate(async_db, "discharge_record")
    assert r["total"] == 1 and r["on_time"] == 1, \
        "出院记录被按入院时刻起算，住院两天就必然判不达标"


@pytest.mark.asyncio
async def test_未办出院的病人不计入出院记录分母(async_db):
    """起算点还不存在，不是"不达标"，是"还没到该算的时候"——计进分母会把
    在院病人算成全员超时，达标率被系统性压低。"""
    await _mk(async_db, record_type="discharge_record", hours_after_start=20,
              discharged=False)
    r = await _rate(async_db, "discharge_record")
    assert r.get("total", 0) == 0, f"未办出院的被计入了分母：{r}"


@pytest.mark.asyncio
async def test_日常病程不纳入时效考核(async_db):
    """RECORD_DEADLINES 只收三类。日常病程没有单条法定时限，纳入即是乱扣分。"""
    await _mk(async_db, record_type="course_record", hours_after_start=99)
    assert "course_record" not in (await get_quality_health(async_db, days=30))["timeliness"]
