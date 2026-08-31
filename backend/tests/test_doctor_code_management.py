# -*- coding: utf-8 -*-
"""HIS 工号绑定管理（2026-09-01 数据更正流程审计新增功能）。

背景：医院给的是**全院名单**，混着自助机、护工、财务，批量开户把护工的工号
挂到临床医生名下是会发生的。而在此之前 DoctorCode 只增不改不删，HIS 派单又按
doctor_codes 定位归属且归属先于状态——不停用那个错账号就继续署错人名，停用则
该工号的推送一律 ack 40007，那位医生的病人再也进不了系统。系统当时给出的提示
是「请联系管理员改派」，而改派功能并不存在。
"""
import pytest
from fastapi import HTTPException

from app.models.user import DoctorCode, User
from app.services import doctor_code_service as svc


async def _mk_user(db, *, username, role="doctor", is_active=True) -> User:
    u = User(username=username, password_hash="x", real_name=username,
             role=role, is_active=is_active)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_改绑把工号从错误账号转到正确医生(async_db):
    wrong = await _mk_user(async_db, username="护工王某")
    right = await _mk_user(async_db, username="李医生")
    async_db.add(DoctorCode(user_id=wrong.id, code="6069", note="批量导入"))
    await async_db.commit()

    res = await svc.reassign_code(async_db, code="6069", target_user_id=right.id)
    assert res["from"]["real_name"] == "护工王某"
    assert res["to"]["real_name"] == "李医生"

    now = await svc.list_codes(async_db, code="6069")
    assert now[0]["user_id"] == right.id


@pytest.mark.asyncio
async def test_不能改绑到已停用账号(async_db):
    """改绑到停用账号只是把问题挪个位置——HIS 推送照样 ack 40007。
    在绑定这一刻拦下来，好过等 HIS 推第一个病人时才发现。"""
    a = await _mk_user(async_db, username="A医生")
    b = await _mk_user(async_db, username="B医生", is_active=False)
    async_db.add(DoctorCode(user_id=a.id, code="6019"))
    await async_db.commit()

    with pytest.raises(HTTPException) as ei:
        await svc.reassign_code(async_db, code="6019", target_user_id=b.id)
    assert ei.value.status_code == 400
    assert "停用" in ei.value.detail


@pytest.mark.asyncio
async def test_不能改绑到非临床角色(async_db):
    """判据与 admit_service 定位归属时一一对应：推到非医生账号会被拒收。"""
    a = await _mk_user(async_db, username="A医生")
    nurse = await _mk_user(async_db, username="护士", role="nurse")
    async_db.add(DoctorCode(user_id=a.id, code="6029"))
    await async_db.commit()

    with pytest.raises(HTTPException) as ei:
        await svc.reassign_code(async_db, code="6029", target_user_id=nurse.id)
    assert ei.value.status_code == 400
    assert "临床医生" in ei.value.detail


@pytest.mark.asyncio
async def test_新增已被占用的工号要指明当前归属(async_db):
    """工号全局唯一。报错里带上当前归属，操作者一眼就知道该走改绑而不是新增。"""
    a = await _mk_user(async_db, username="汪医生")
    b = await _mk_user(async_db, username="濮医生")
    async_db.add(DoctorCode(user_id=a.id, code="16029"))
    await async_db.commit()

    with pytest.raises(HTTPException) as ei:
        await svc.bind_code(async_db, user_id=b.id, code="16029")
    assert ei.value.status_code == 409
    assert "汪医生" in ei.value.detail


@pytest.mark.asyncio
async def test_一位医生可以挂多个工号(async_db):
    """安吉濮氏真实名单：汪来煜 6069(门诊)/16029(住院)/16039(助理)。
    所以这里是「新增」而不是「替换」——替换会把另外两个号弄丢。"""
    doc = await _mk_user(async_db, username="汪来煜")
    for code, note in [("6069", "本人·门诊"), ("16029", "本人·住院"), ("16039", "助理")]:
        await svc.bind_code(async_db, user_id=doc.id, code=code, note=note)

    codes = await svc.list_codes(async_db, user_id=doc.id)
    assert {c["code"] for c in codes} == {"6069", "16029", "16039"}


@pytest.mark.asyncio
async def test_解绑后该工号查不到归属(async_db):
    """用于误导入的护工/自助机工号：解绑后 HIS 再推会 ack 40007 并带上工号，
    让厂商侧发现推错了号——而不是让病历落到某个医生名下。"""
    a = await _mk_user(async_db, username="财务张某")
    async_db.add(DoctorCode(user_id=a.id, code="9999"))
    await async_db.commit()

    await svc.unbind_code(async_db, code="9999")
    assert await svc.list_codes(async_db, code="9999") == []


@pytest.mark.asyncio
async def test_改绑不影响历史病历署名(async_db):
    """核心不变量：已产生的接诊/病历按 doctor_id 存，不经过 doctor_codes。
    改绑只影响此后的 HIS 推送归属——法定文书签发时是谁就永远是谁，
    绝不能因为改了工号绑定就把历史病历的署名追溯性地改掉。"""
    from datetime import datetime

    from app.models.encounter import Encounter
    from app.models.patient import Patient

    wrong = await _mk_user(async_db, username="错绑医生")
    right = await _mk_user(async_db, username="正确医生")
    patient = Patient(name="测试患者", gender="male")
    async_db.add(patient)
    await async_db.flush()
    enc = Encounter(patient_id=patient.id, doctor_id=wrong.id,
                    visit_type="outpatient", visited_at=datetime.now())
    async_db.add(enc)
    async_db.add(DoctorCode(user_id=wrong.id, code="7001"))
    await async_db.commit()

    await svc.reassign_code(async_db, code="7001", target_user_id=right.id)
    await async_db.refresh(enc)
    assert enc.doctor_id == wrong.id, "改绑把历史接诊的医生也改了——法定署名不得追溯变更"
