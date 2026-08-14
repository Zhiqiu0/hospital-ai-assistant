"""接诊科室以挂号科室为准（2026-08-14 用户决策）。

规范 3.1 对 dept_code 的说明是「本次接诊/挂号的科室，**非医生编制科室**」，
并要求厂商去科室表取「本地ID」列推给我们。但代码原先直接用
doctor.department_id —— 恰恰是规范明确排除的那个，dept_code 只被原样塞进
JSONB 从不解析。

本院医生存在**跨科室坐班**：人在外科坐班时，病历上却写着他编制所在的内科。
"""

import pytest
from sqlalchemy import select

from app.his_adapter.admit_service import process_admit
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.user import Department, User


def _payload(**over):
    base = {
        "visit_id": "V20260814001",
        "hospital_code": "H33052300957",
        "patient_name": "张三",
        "gender": "male",
        "doctor_code": "D1001",
        "dept_code": "1230024",
        "dept_name": "全科",
    }
    base.update(over)
    return AdmitPushRequest(**base)


async def _mk_doctor(db, *, dept_id=None):
    doctor = User(
        username="doc1", password_hash="x", real_name="王医生",
        role="doctor", employee_no="D1001", is_active=True,
        department_id=dept_id,
    )
    db.add(doctor)
    await db.commit()
    return doctor


@pytest.mark.asyncio
async def test_接诊科室用挂号科室而非医生编制科室(async_db):
    """医生编制在内科，这次在全科坐班 → 接诊科室必须是全科。"""
    nei = Department(id="d-nei", name="内科", code="NK")
    async_db.add(nei)
    await async_db.commit()
    await _mk_doctor(async_db, dept_id="d-nei")

    result = await process_admit(async_db, _payload())

    enc = await async_db.get(Encounter, result.encounter_id)
    dept = await async_db.get(Department, enc.department_id)
    assert dept.code == "1230024", "接诊科室仍是医生编制科室，跨科室坐班时病历科室会错"
    assert dept.name == "全科"


@pytest.mark.asyncio
async def test_首次见到的科室自动建档(async_db):
    """附录 B 已确认无需科室字典——code+name 随每次推送成对下发，见到就落一条。"""
    await _mk_doctor(async_db)

    await process_admit(async_db, _payload(dept_code="9999001", dept_name="新开的康复科"))

    dept = (await async_db.execute(
        select(Department).where(Department.code == "9999001")
    )).scalar_one()
    assert dept.name == "新开的康复科"
    assert dept.is_active is True


@pytest.mark.asyncio
async def test_同一科室重复推送不重复建档(async_db):
    await _mk_doctor(async_db)

    await process_admit(async_db, _payload(visit_id="V1"))
    await process_admit(async_db, _payload(visit_id="V2"))

    rows = (await async_db.execute(
        select(Department).where(Department.code == "1230024")
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_his改了科室名会跟着更新(async_db):
    """code 才是身份，name 只是展示。"""
    await _mk_doctor(async_db)

    await process_admit(async_db, _payload(visit_id="V1", dept_name="全科"))
    await process_admit(async_db, _payload(visit_id="V2", dept_name="全科医学科"))

    dept = (await async_db.execute(
        select(Department).where(Department.code == "1230024")
    )).scalar_one()
    assert dept.name == "全科医学科"


@pytest.mark.asyncio
async def test_没推科室时回退医生编制科室(async_db):
    """厂商漏推 dept_code 也不能让接诊建不出来。"""
    nei = Department(id="d-nei", name="内科", code="NK")
    async_db.add(nei)
    await async_db.commit()
    await _mk_doctor(async_db, dept_id="d-nei")

    result = await process_admit(async_db, _payload(dept_code=None, dept_name=None))

    enc = await async_db.get(Encounter, result.encounter_id)
    assert enc.department_id == "d-nei"
