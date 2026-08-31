# -*- coding: utf-8 -*-
"""重复患者档案合并（2026-09-01 数据更正流程审计新增功能）。

背景：三级查重强键（身份证 / 院内主索引 / 手机号+姓名）全 miss 时系统会新建
档案——老人无身份证、儿童留家长手机、代挂号都会触发。这是刻意取舍，但代码里
三处注释写的「可事后人工合并」**从来没有实现过**。后果是过敏史/既往史分散在
两份档案下，医生查复诊史只看得到一半，而过敏史正是开药前飘红警示的那个字段。

本文件锁住服务的三条设计红线：
  ① 不可逆 → 确认姓名不匹配必须拒绝
  ② 已签发病历的 patient_snapshot 绝不改动（法定署名，且进了 sign_hash）
  ③ 档案字段只补空不覆盖（不能悄悄改掉医生确认过的过敏史）
"""
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.imaging import ImagingStudy
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.services import patient_merge_service as svc


async def _mk_patient(db, **kw) -> Patient:
    p = Patient(**kw)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@pytest.mark.asyncio
async def test_合并把接诊与影像搬到目标档案(async_db):
    target = await _mk_patient(async_db, name="周八", gender="male")
    source = await _mk_patient(async_db, name="周八", gender="male")
    async_db.add(Encounter(patient_id=source.id, doctor_id="d1",
                           visit_type="outpatient", visited_at=datetime.now()))
    async_db.add(ImagingStudy(patient_id=source.id, study_instance_uid="1.2.3",
                              uploaded_by="d1"))
    await async_db.commit()

    res = await svc.merge(async_db, target_id=target.id, source_id=source.id,
                          confirm_name="周八", operator_id="admin-1")
    assert res["moved"] == {"encounters": 1, "imaging_studies": 1}

    moved = (await async_db.execute(
        select(Encounter).where(Encounter.patient_id == target.id))).scalars().all()
    assert len(moved) == 1
    await async_db.refresh(source)
    assert source.is_deleted is True
    assert source.merged_into == target.id


@pytest.mark.asyncio
async def test_确认姓名不匹配直接拒绝(async_db):
    """合并不可逆，误合并两个真人无法撤销——这道确认是防误点的最后一关。"""
    target = await _mk_patient(async_db, name="吴九", gender="male")
    source = await _mk_patient(async_db, name="郑十", gender="male")
    with pytest.raises(HTTPException) as ei:
        await svc.merge(async_db, target_id=target.id, source_id=source.id,
                        confirm_name="吴九", operator_id="admin-1")
    assert ei.value.status_code == 400
    await async_db.refresh(source)
    assert source.is_deleted is False, "确认失败却已经改动了数据"


@pytest.mark.asyncio
async def test_档案字段只补空不覆盖(async_db):
    """target 是保留下来的那份，以它为准。合并不能悄悄改掉医生已确认的过敏史。"""
    target = await _mk_patient(async_db, name="钱一", gender="male",
                               profile_allergy_history="青霉素过敏")
    source = await _mk_patient(async_db, name="钱一", gender="male",
                               profile_allergy_history="否认过敏史",
                               profile_past_history="高血压 10 年")
    await svc.merge(async_db, target_id=target.id, source_id=source.id,
                    confirm_name="钱一", operator_id="admin-1")

    await async_db.refresh(target)
    assert target.profile_allergy_history == "青霉素过敏", "已有值被覆盖了"
    assert target.profile_past_history == "高血压 10 年", "空字段没有补上"


@pytest.mark.asyncio
async def test_已签发病历的患者快照不受影响(async_db):
    """快照签发瞬间冻结并进 sign_hash，是法定文书的署名来源。改它会让
    verify_chain 把这份病历永久报为「内容被篡改」。"""
    target = await _mk_patient(async_db, name="孙二", gender="male")
    source = await _mk_patient(async_db, name="孙贰", gender="male")
    enc = Encounter(patient_id=source.id, doctor_id="d1",
                    visit_type="outpatient", visited_at=datetime.now())
    async_db.add(enc)
    await async_db.flush()
    snap = {"name": "孙贰", "gender": "male"}
    rec = MedicalRecord(encounter_id=enc.id, record_type="outpatient",
                        status="submitted", current_version=1, record_no=1,
                        patient_snapshot=snap)
    async_db.add(rec)
    await async_db.commit()

    await svc.merge(async_db, target_id=target.id, source_id=source.id,
                    confirm_name="孙贰", operator_id="admin-1")

    await async_db.refresh(rec)
    assert rec.patient_snapshot == snap, "合并改动了已签发病历的法定署名快照"


@pytest.mark.asyncio
async def test_预览会对身份证不一致发出警告(async_db):
    """两份档案的身份证都存在且不同，几乎可以断定是两个人——必须让人看见。"""
    target = await _mk_patient(async_db, name="李三", gender="male",
                               id_card="330101199001011234",
                               birth_date=date(1990, 1, 1))
    source = await _mk_patient(async_db, name="李三", gender="male",
                               id_card="330101198505054321",
                               birth_date=date(1985, 5, 5))
    res = await svc.preview(async_db, target_id=target.id, source_id=source.id)
    joined = " ".join(res["warnings"])
    assert "身份证" in joined
    assert "出生日期" in joined
    assert res["confirm_hint"].count("李三") == 1


@pytest.mark.asyncio
async def test_预览不改动任何数据(async_db):
    target = await _mk_patient(async_db, name="赵四", gender="male")
    source = await _mk_patient(async_db, name="赵四", gender="male")
    await svc.preview(async_db, target_id=target.id, source_id=source.id)
    await async_db.refresh(source)
    assert source.is_deleted is False
    assert source.merged_into is None


@pytest.mark.asyncio
async def test_不能合并已被合并过的档案(async_db):
    a = await _mk_patient(async_db, name="王五", gender="male")
    b = await _mk_patient(async_db, name="王五", gender="male")
    c = await _mk_patient(async_db, name="王五", gender="male")
    await svc.merge(async_db, target_id=a.id, source_id=b.id,
                    confirm_name="王五", operator_id="admin-1")
    with pytest.raises(HTTPException):
        await svc.merge(async_db, target_id=c.id, source_id=b.id,
                        confirm_name="王五", operator_id="admin-1")


@pytest.mark.asyncio
async def test_不能自己合并自己(async_db):
    p = await _mk_patient(async_db, name="冯六", gender="male")
    with pytest.raises(HTTPException):
        await svc.merge(async_db, target_id=p.id, source_id=p.id,
                        confirm_name="冯六", operator_id="admin-1")
