# -*- coding: utf-8 -*-
"""同 visit_id 重推时的患者信息处理（2026-09-02 HIS 异常面演练发现）。

原实现在幂等复用分支里只处理医生改派，患者信息一个字段都不看——同一个
visit_id 推来不同的姓名/身份证，静默忽略且无任何告警。生产实测：推「甲」后
再推「乙」+身份证，库里仍是「甲」、身份证仍为空、日志无痕。

两个现实后果：
  ① 急诊无名氏补不回来。本模块写了"姓名不可清洗 → 占位名『未知患者』"的降级
     路径，而 HIS 补齐姓名后重推同一 visit_id 正是最自然的补救方式——被忽略后
     那位患者永远叫"未知患者"，身份证也补不进来，跨就诊认人（靠 id_card /
     patient_no）随之失效，他下次来还是新建档案。
  ② 挂错号纠正后我方不跟。HIS 把张三改成李四重推，工作台仍显示张三，医生对着
     错的患者写病历。

口径与档案合并一致：补空不覆盖；两边都有值且不同则不覆盖，但必须留痕告警。
"""
from datetime import date

import pytest
from sqlalchemy import select

from app.his_adapter import admit_service
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import DoctorCode, User


@pytest.fixture
async def _doc(async_db):
    u = User(id="his-doc", username="hisdoc", password_hash="x", real_name="推送医生",
             role="doctor", is_active=True, employee_no="HD01")
    async_db.add(u)
    await async_db.flush()
    async_db.add(DoctorCode(user_id=u.id, code="HD01"))
    await async_db.commit()
    return u


def _push(**kw) -> AdmitPushRequest:
    base = {"visit_id": "V-REPUSH", "hospital_code": "H001", "doctor_code": "HD01"}
    base.update(kw)
    return AdmitPushRequest(**base)


async def _patient_of(db, enc_id):
    enc = await db.get(Encounter, enc_id)
    return await db.get(Patient, enc.patient_id)


@pytest.mark.asyncio
async def test_无名氏重推补齐姓名与身份证(async_db, _doc):
    """急诊三无人员先以占位名建档，HIS 补齐信息后重推——必须补上。"""
    r1 = await admit_service.process_admit(async_db, _push(patient_name=None))
    p = await _patient_of(async_db, r1.encounter_id)
    assert p.name == "未知患者", "前提不成立：无名氏没走占位名降级"

    r2 = await admit_service.process_admit(async_db, _push(
        patient_name="李建国", id_card="330523195003128116",
        birth_date="1950-03-12", patient_no="MPI0001"))
    assert r2.encounter_id == r1.encounter_id, "重推不该新建接诊"
    p = await _patient_of(async_db, r2.encounter_id)
    assert p.name == "李建国", "占位名没被补齐，患者永远叫「未知患者」"
    assert p.id_card == "330523195003128116", "身份证没补上，跨就诊认人仍会失效"
    assert p.patient_no == "MPI0001"
    assert p.birth_date == date(1950, 3, 12), "生日没补上——年龄影响用药判断"


@pytest.mark.asyncio
async def test_姓名冲突不覆盖但留痕(async_db, _doc):
    """两边都有值且不同：以谁为准是业务口径，代码不替医院决定——但必须查得到。"""
    r1 = await admit_service.process_admit(async_db, _push(patient_name="张三"))
    r2 = await admit_service.process_admit(async_db, _push(
        patient_name="李四", visit_id="V-REPUSH"))
    p = await _patient_of(async_db, r2.encounter_id)
    assert p.name == "张三", "已有姓名被静默覆盖了"
    enc = await async_db.get(Encounter, r1.encounter_id)
    conflicts = (enc.his_external_ref or {}).get("patient_conflicts") or []
    assert any("张三" in c and "李四" in c for c in conflicts), \
        "冲突没留痕，事后无法追查 HIS 说的是谁"


@pytest.mark.asyncio
async def test_已有身份证不被重推改掉(async_db, _doc):
    await admit_service.process_admit(async_db, _push(
        patient_name="王五", id_card="330523198001011233"))
    r2 = await admit_service.process_admit(async_db, _push(
        patient_name="王五", id_card="330523199912310001"))
    p = await _patient_of(async_db, r2.encounter_id)
    assert p.id_card == "330523198001011233", "身份证被重推悄悄改掉了"


@pytest.mark.asyncio
async def test_重推同样内容不产生冲突留痕(async_db, _doc):
    """医生在 HIS 里反复打开患者会重推同一份数据，这是最常见的重推形态，
    不能把它记成冲突把日志刷满。"""
    same = dict(patient_name="赵六", id_card="330523197505050012")
    r1 = await admit_service.process_admit(async_db, _push(**same))
    await admit_service.process_admit(async_db, _push(**same))
    enc = await async_db.get(Encounter, r1.encounter_id)
    assert not (enc.his_external_ref or {}).get("patient_conflicts")


@pytest.mark.asyncio
async def test_校验不过的身份证不得从重推溜进档案(async_db, _doc):
    """首次建档时 id_card 要过 PatientCreate（含 GB 11643 校验位），不过就丢弃。
    补空路径若直接赋值就绕过了这层——而身份证正是跨就诊认人的强键，错的比没有
    更糟：它会把两个不同的人认成同一个。（写这条补空逻辑时正是先这么错的。）"""
    r1 = await admit_service.process_admit(async_db, _push(patient_name="孙七"))
    p = await _patient_of(async_db, r1.encounter_id)
    assert not p.id_card

    await admit_service.process_admit(async_db, _push(
        patient_name="孙七", id_card="330523198001011234"))   # 校验位错误
    p = await _patient_of(async_db, r1.encounter_id)
    assert not p.id_card, "校验位错误的身份证被补进了档案"
