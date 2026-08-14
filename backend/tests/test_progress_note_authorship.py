"""病程记录署名跟随实际书写人（2026-08-14 第八轮审计 high）。

真实形态：白班 A 医生在时间轴点一下「日常病程」建了条空草稿就下班了
（前端建的就是 content='' 的立即建条），夜班接手的 B 医生打开它、写完全部
正文、点签发——修复前这条病程的书写医生仍是 A，且签发即冻结无法更正。

recorded_by 是 ProgressNote **唯一**的署名字段（没有版本表、没有 triggered_by、
没有患者快照）。30 天住院里换管床、值班交接是常态，而医院的硬要求是
「病历上写的名字必须是本人」。
"""

from datetime import date, datetime

import pytest

from app.models.encounter import Encounter
from app.models.patient import Patient
from app.services import progress_notes_service as svc


@pytest.fixture
def seeded_ids():
    return "enc-1"


async def _seed(db):
    db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-A",
        visit_type="inpatient", status="in_progress",
        visited_at=datetime(2026, 8, 1),
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_接手医生写完正文后署名变成他自己(async_db):
    await _seed(async_db)
    note = await svc.create_note(
        async_db, encounter_id="enc-1", note_type="daily_course",
        title=None, content="", recorded_at_raw=None, recorded_by="张三医生",
    )
    assert note.recorded_by == "张三医生"

    updated = await svc.update_note(
        async_db, encounter_id="enc-1", note_id=note.id,
        title=None, content="李四医生写的查房病程正文", status=None,
        recorded_at_raw=None, editor_name="李四医生",
    )
    assert updated.recorded_by == "李四医生", "交接后署名仍是前一位医生"


@pytest.mark.asyncio
async def test_签发时署名保持为实际书写人(async_db):
    await _seed(async_db)
    note = await svc.create_note(
        async_db, encounter_id="enc-1", note_type="daily_course",
        title=None, content="", recorded_at_raw=None, recorded_by="张三医生",
    )
    await svc.update_note(
        async_db, encounter_id="enc-1", note_id=note.id,
        title=None, content="李四写完的正文", status=None,
        recorded_at_raw=None, editor_name="李四医生",
    )
    signed = await svc.update_note(
        async_db, encounter_id="enc-1", note_id=note.id,
        title=None, content=None, status="submitted",
        recorded_at_raw=None, editor_name="李四医生",
    )
    assert signed.status == "submitted"
    assert signed.recorded_by == "李四医生"


@pytest.mark.asyncio
async def test_只改状态不改正文时不动署名(async_db):
    """本人建、本人写、别人只点了签发——署名仍是写的人，不该被点签发的人顶掉。"""
    await _seed(async_db)
    note = await svc.create_note(
        async_db, encounter_id="enc-1", note_type="daily_course",
        title=None, content="张三自己写完的正文", recorded_at_raw=None,
        recorded_by="张三医生",
    )
    signed = await svc.update_note(
        async_db, encounter_id="enc-1", note_id=note.id,
        title=None, content=None, status="submitted",
        recorded_at_raw=None, editor_name="护士长",
    )
    assert signed.recorded_by == "张三医生"


@pytest.mark.asyncio
async def test_空正文的占位条不改署名(async_db):
    """没人写过内容的占位条，不因为一次空更新就改署名。"""
    await _seed(async_db)
    note = await svc.create_note(
        async_db, encounter_id="enc-1", note_type="daily_course",
        title=None, content="", recorded_at_raw=None, recorded_by="张三医生",
    )
    updated = await svc.update_note(
        async_db, encounter_id="enc-1", note_id=note.id,
        title="改个标题", content="   ", status=None,
        recorded_at_raw=None, editor_name="李四医生",
    )
    assert updated.recorded_by == "张三医生"
