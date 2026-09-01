# -*- coding: utf-8 -*-
"""补记标注必须能到达打印件（2026-09-02 住院支线实测发现）。

《病历书写基本规范》第七条：因抢救急危患者未能及时书写病历的，应当在抢救结束
后 6 小时内**据实补记，并加以注明**。

「注明」的载体是归档病历本身——而归档进病案室、被质控员翻阅、被法庭调阅的是
**打印件**，不是屏幕。实测发现：补记徽标只存在于住院工作台的时间轴组件里，
而打印/Word 导出走的是 _paginate_records 这条序列化，它根本不下发
recorded_at / entered_at / is_late_entry。结果是一份隔天补写的病程，打出来与
当场书写的完全无法区分——规范要求的「注明」在纸面上不存在。

本文件锁住数据源那一端（前端渲染由 recordExport 的类型契约保证）。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.services.medical_record_service import MedicalRecordService


async def _mk(db, *, back_hours: float) -> str:
    """建一份记录时点比系统录入时点早 back_hours 小时的病历。"""
    p = Patient(name="补记打印", gender="male")
    db.add(p)
    await db.flush()
    enc = Encounter(patient_id=p.id, doctor_id="doc-1", visit_type="inpatient",
                    visited_at=datetime.now())
    db.add(enc)
    await db.flush()
    svc = MedicalRecordService(db)
    await svc.auto_save_draft(
        encounter_id=enc.id, record_type="course_record", content="病程正文",
        user_id="doc-1",
        recorded_at=datetime.now() - timedelta(hours=back_hours),
    )
    # list_by_patient 只列已签发的（打印/归档的正是这一类），故签发后再查
    rec = (await db.execute(
        select(MedicalRecord).where(MedicalRecord.encounter_id == enc.id)
    )).scalar_one()
    assert rec.recorded_at is not None
    rec.status = "submitted"
    rec.submitted_at = datetime.now()
    await db.commit()
    return p.id


async def _item(db, patient_id: str) -> dict:
    res = await MedicalRecordService(db).list_by_patient(patient_id)
    return res["items"][0] if isinstance(res, dict) else res[0]


@pytest.mark.asyncio
async def test_打印数据源下发补记三元组(async_db):
    """三个字段缺一不可：只给 is_late_entry 而不给两个时间，纸面就只能写
    「本文书为补记」——而规范要的是「原记录保持可见」，两个时点都得露出来。"""
    item = await _item(async_db, await _mk(async_db, back_hours=24))
    assert item["is_late_entry"] is True, "隔天补写的病程没被标为补记"
    assert item["recorded_at"], "缺记录时点，纸面写不出补记的是哪天的事"
    assert item["entered_at"], "缺系统录入时点，无法佐证补记发生在何时"


@pytest.mark.asyncio
async def test_当场书写不带补记标注(async_db):
    """夜班 23:50 记当天 20:00 的查房是正常书写，纸面上不能印补记——
    误标的代价和漏标一样重：质控和法庭会把正常病历当成可疑证据。"""
    item = await _item(async_db, await _mk(async_db, back_hours=3))
    assert item["is_late_entry"] is False


@pytest.mark.asyncio
async def test_阈值边界之内不标(async_db):
    """11.5 小时 < 12 小时阈值。"""
    item = await _item(async_db, await _mk(async_db, back_hours=11.5))
    assert item["is_late_entry"] is False
