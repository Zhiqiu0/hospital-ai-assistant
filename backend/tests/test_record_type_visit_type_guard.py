# -*- coding: utf-8 -*-
"""文书类型必须与就诊类型相容（2026-09-01 住院支线端到端实测发现）。

复现路径很自然：在急诊工作台签发完一份病历、不做任何清理，直接访问 /inpatient。
三个工作台共用同一个 activeEncounterStore，切系统时不清当前接诊，而住院页的
visitTypeFilter 只用于**续接诊列表筛选**、不校验当前接诊——于是住院工作台把那个
visit_type=emergency 的接诊当住院病人显示，标成「住院 #xxx」，还给它算
「入院记录剩余 19.4 小时」的住院文书时效。

此时医生继续操作，就会给一个急诊接诊挂上 admission_note 这类住院文书，而后端
此前对此**没有任何校验**（_is_inpatient 只决定"能否多份同类型文书"，不管类型
对不对）。落库后果是连锁的：病案首页与归档口径错乱、HIS 回写把"入院记录"推给
一个急诊 visit_id、质控拿住院评分标准去判一份急诊病历。

生产库实测当时无错配，属于"尚未发生但路径已通"，按「病历不能出问题」先堵上。
"""
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models.encounter import Encounter
from app.models.patient import Patient
from app.services._record_type_guard import (
    ALLOWED_RECORD_TYPES,
    assert_record_type_matches,
)
from app.services.medical_record_service import MedicalRecordService


# ── 纯函数层 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("visit_type,record_type", [
    ("outpatient", "outpatient"),
    ("emergency", "emergency"),
    ("inpatient", "admission_note"),
    ("inpatient", "course_record"),
    ("inpatient", "discharge_record"),
])
def test_相容组合放行(visit_type, record_type):
    assert_record_type_matches(visit_type, record_type)


@pytest.mark.parametrize("visit_type,record_type", [
    ("emergency", "admission_note"),   # 实测路径：急诊接诊被带进住院工作台
    ("outpatient", "course_record"),
    ("inpatient", "outpatient"),
    ("outpatient", "emergency"),
])
def test_不相容组合拒绝(visit_type, record_type):
    with pytest.raises(HTTPException) as ei:
        assert_record_type_matches(visit_type, record_type)
    assert ei.value.status_code == 400
    assert "不符" in ei.value.detail


def test_未知就诊类型放行():
    """None / 历史遗留值一律放行——守卫的职责是拦已知的错配，不是给老数据添堵。"""
    assert_record_type_matches(None, "outpatient")
    assert_record_type_matches("legacy_type", "admission_note")


def test_住院文书清单与模型枚举一致():
    """住院那组必须覆盖全部住院文书类型，漏一个就会把合法书写拦下来。"""
    assert ALLOWED_RECORD_TYPES["inpatient"] == {
        "admission_note", "first_course_record", "course_record", "senior_round",
        "pre_op_summary", "op_record", "post_op_record", "discharge_record",
    }


# ── 草稿写入路径 ────────────────────────────────────────────────────────

async def _mk_encounter(db, visit_type: str) -> str:
    p = Patient(name="守卫测试", gender="male")
    db.add(p)
    await db.flush()
    e = Encounter(patient_id=p.id, doctor_id="d1", visit_type=visit_type,
                  visited_at=datetime.now())
    db.add(e)
    await db.commit()
    return e.id


@pytest.mark.asyncio
async def test_急诊接诊不能存住院文书草稿(async_db):
    """这正是实测走出来的那条路径。"""
    enc_id = await _mk_encounter(async_db, "emergency")
    with pytest.raises(HTTPException) as ei:
        await MedicalRecordService(async_db).auto_save_draft(
            encounter_id=enc_id, record_type="admission_note",
            content="入院记录正文", user_id="d1")
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_住院接诊正常存住院文书(async_db):
    enc_id = await _mk_encounter(async_db, "inpatient")
    res = await MedicalRecordService(async_db).auto_save_draft(
        encounter_id=enc_id, record_type="admission_note",
        content="入院记录正文", user_id="d1")
    assert res["record_id"]


@pytest.mark.asyncio
async def test_门诊接诊正常存门诊病历(async_db):
    enc_id = await _mk_encounter(async_db, "outpatient")
    res = await MedicalRecordService(async_db).auto_save_draft(
        encounter_id=enc_id, record_type="outpatient",
        content="门诊病历正文", user_id="d1")
    assert res["record_id"]


# ── AI 生成写入路径（第三条，最初漏掉的那条）─────────────────────────────

@pytest.mark.asyncio
async def test_住院接诊不能存门诊病历_AI生成路径(async_db):
    """实测就是从这条漏进去的：住院工作台新建接诊后 recordType 保持默认
    'outpatient'，医生直接填问诊点生成，AI 落库走 save_ai_draft——而当时守卫
    只加在 auto_save_draft 与 quick_save 上，这条没拦，于是住院接诊下真的躺了
    一份 record_type='outpatient' 的病历。三条写入路径必须同口径。"""
    enc_id = await _mk_encounter(async_db, "inpatient")
    with pytest.raises(HTTPException) as ei:
        await MedicalRecordService(async_db).save_ai_draft(
            encounter_id=enc_id, record_type="outpatient",
            content="AI 生成的门诊病历正文", user_id="d1")
    assert ei.value.status_code == 400


@pytest.mark.asyncio
async def test_住院接诊AI生成入院记录正常(async_db):
    enc_id = await _mk_encounter(async_db, "inpatient")
    res = await MedicalRecordService(async_db).save_ai_draft(
        encounter_id=enc_id, record_type="admission_note",
        content="入院记录正文", user_id="d1")
    assert res["record_id"]


@pytest.mark.asyncio
async def test_三条写入路径同口径(async_db):
    """草稿 / AI 生成 / 签发——任一条漏了守卫，脏数据都能进来。"""
    svc = MedicalRecordService(async_db)
    enc_id = await _mk_encounter(async_db, "emergency")
    for call in (
        lambda: svc.auto_save_draft(encounter_id=enc_id, record_type="admission_note",
                                    content="x", user_id="d1"),
        lambda: svc.save_ai_draft(encounter_id=enc_id, record_type="admission_note",
                                  content="x", user_id="d1"),
    ):
        with pytest.raises(HTTPException) as ei:
            await call()
        assert ei.value.status_code == 400
