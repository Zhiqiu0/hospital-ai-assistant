"""接诊推送业务落地单测（his_adapter/admit_service.py）。

覆盖：医生映射（employee_no / username 兜底 / 未注册拒收）、患者三级查重复用、
新建患者标记 is_from_his、visit_id 幂等、脏身份证降级、visit_type 口径映射。
"""
import pytest
from sqlalchemy import select

from app.his_adapter.admit_service import AdmitError, process_admit
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User


def _payload(**overrides) -> AdmitPushRequest:
    """构造最小合法接诊推送载荷，字段可覆盖。"""
    base = {
        "visit_id": "20260811000101",
        "hospital_code": "H33052300957",
        "patient_name": "张三",
        "gender": "male",
        "doctor_code": "D1001",
        "dept_code": "1230024",
        "dept_name": "全科",
    }
    base.update(overrides)
    return AdmitPushRequest(**base)


async def _mk_doctor(db, *, username="doc1", employee_no="D1001") -> User:
    """建一个激活状态的医生账号。"""
    doctor = User(
        username=username, password_hash="x", real_name="王医生",
        role="doctor", employee_no=employee_no, is_active=True,
    )
    db.add(doctor)
    await db.commit()
    await db.refresh(doctor)
    return doctor


@pytest.mark.asyncio
async def test_admit_creates_patient_and_encounter(async_db):
    """新患者推送 → 建档（is_from_his=True，性别转中文）+ 建接诊（落 HIS 上下文）。"""
    doctor = await _mk_doctor(async_db)
    result = await process_admit(async_db, _payload())

    assert result.reused is False
    assert result.doctor_id == doctor.id
    patient = await async_db.get(Patient, result.patient_id)
    assert patient.name == "张三"
    assert patient.gender == "男"
    assert patient.is_from_his is True
    enc = await async_db.get(Encounter, result.encounter_id)
    assert enc.visit_no == "20260811000101"
    assert enc.visit_type == "outpatient"
    assert enc.his_external_ref["source"] == "admit_push"
    assert enc.his_external_ref["dept_name"] == "全科"


@pytest.mark.asyncio
async def test_admit_unmapped_doctor_rejected(async_db):
    """医生工号未注册 → AdmitError(40007)。"""
    with pytest.raises(AdmitError) as exc_info:
        await process_admit(async_db, _payload(doctor_code="D404"))
    assert exc_info.value.code == 40007
    assert "D404" in exc_info.value.message


@pytest.mark.asyncio
async def test_admit_missing_doctor_code_rejected(async_db):
    """推送缺 doctor_code → AdmitError(40007)。"""
    with pytest.raises(AdmitError) as exc_info:
        await process_admit(async_db, _payload(doctor_code=None))
    assert exc_info.value.code == 40007


@pytest.mark.asyncio
async def test_admit_doctor_matched_by_username_fallback(async_db):
    """employee_no 未回填时，用户名=工号 兜底匹配（批量开户约定）。"""
    doctor = await _mk_doctor(async_db, username="D2002", employee_no=None)
    result = await process_admit(async_db, _payload(doctor_code="D2002"))
    assert result.doctor_id == doctor.id


@pytest.mark.asyncio
async def test_admit_visit_id_idempotent(async_db):
    """同 visit_id 重复推送 → 复用现存接诊，不重复建档。"""
    await _mk_doctor(async_db)
    first = await process_admit(async_db, _payload())
    second = await process_admit(async_db, _payload())

    assert second.reused is True
    assert second.encounter_id == first.encounter_id
    count = (await async_db.execute(select(Encounter))).scalars().all()
    assert len(count) == 1
    patients = (await async_db.execute(select(Patient))).scalars().all()
    assert len(patients) == 1


@pytest.mark.asyncio
async def test_admit_patient_dedup_by_id_card(async_db):
    """同身份证不同就诊 → 复用患者档案，只建新接诊。"""
    await _mk_doctor(async_db)
    id_card = "330523199001011238"  # 校验位合法的测试号
    first = await process_admit(
        async_db, _payload(id_card=id_card, birth_date="1990-01-01"))
    second = await process_admit(
        async_db, _payload(visit_id="20260811000102", id_card=id_card,
                           birth_date="1990-01-01"))
    assert second.patient_id == first.patient_id
    assert second.encounter_id != first.encounter_id


@pytest.mark.asyncio
async def test_admit_dirty_id_card_dropped(async_db):
    """HIS 推来的身份证过不了严格校验 → 丢弃该字段建档，不拒收接诊。"""
    await _mk_doctor(async_db)
    result = await process_admit(async_db, _payload(id_card="123456"))
    patient = await async_db.get(Patient, result.patient_id)
    assert patient.id_card is None
    assert patient.name == "张三"


@pytest.mark.asyncio
async def test_admit_visit_type_chinese_mapped(async_db):
    """visit_type 中文口径（急诊）→ 收敛为 emergency。"""
    await _mk_doctor(async_db)
    result = await process_admit(async_db, _payload(visit_type="急诊"))
    enc = await async_db.get(Encounter, result.encounter_id)
    assert enc.visit_type == "emergency"


@pytest.mark.asyncio
async def test_admit_cancelled_encounter_not_reused(async_db):
    """现存同 visit_id 接诊已取消 → 视为新接诊重建（医生误取消后 HIS 重推）。"""
    await _mk_doctor(async_db)
    first = await process_admit(async_db, _payload())
    enc = await async_db.get(Encounter, first.encounter_id)
    enc.status = "cancelled"
    await async_db.commit()

    second = await process_admit(async_db, _payload())
    assert second.reused is False
    assert second.encounter_id != first.encounter_id
