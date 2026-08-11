"""审计修复的行为测试（2026-08-11）：quick_save 状态守卫 + HIS 查重收紧。"""
import pytest

from app.his_adapter.admit_service import process_admit
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User
from app.services.medical_record_service import MedicalRecordService


async def _mk_encounter(db, *, status="in_progress", visit_type="outpatient") -> str:
    p = Patient(name="测试患者")
    db.add(p)
    await db.flush()
    doc = User(username="d_sign", password_hash="x", real_name="医生", role="doctor")
    db.add(doc)
    await db.flush()
    enc = Encounter(patient_id=p.id, doctor_id=doc.id, visit_type=visit_type,
                    status=status)
    db.add(enc)
    await db.commit()
    await db.refresh(enc)
    return enc.id, doc.id


@pytest.mark.asyncio
async def test_quick_save_rejects_cancelled_encounter(async_db):
    """已取消接诊不能被签发'复活'（状态守卫）。"""
    enc_id, doc_id = await _mk_encounter(async_db, status="cancelled")
    service = MedicalRecordService(async_db)
    with pytest.raises(ValueError, match="已取消"):
        await service.quick_save(enc_id, "outpatient", "病历正文", doc_id)


@pytest.mark.asyncio
async def test_quick_save_idempotent_on_submitted(async_db):
    """已签发门诊病历重复签发 → 幂等返回原记录，不改写。"""
    enc_id, doc_id = await _mk_encounter(async_db)
    service = MedicalRecordService(async_db)
    r1 = await service.quick_save(enc_id, "outpatient", "第一次", doc_id)
    v1 = r1.current_version
    r2 = await service.quick_save(enc_id, "outpatient", "第二次改写", doc_id)
    assert r2.id == r1.id
    assert r2.current_version == v1  # 版本号未涨，未重复改写


@pytest.mark.asyncio
async def test_quick_save_nonexistent_encounter(async_db):
    """不存在的接诊签发 → ValueError。"""
    service = MedicalRecordService(async_db)
    with pytest.raises(ValueError, match="不存在"):
        await service.quick_save("no-such-enc", "outpatient", "x", "doc-x")


def _admit(**kw) -> AdmitPushRequest:
    base = {"visit_id": "V1", "hospital_code": "H1", "patient_name": "王芳",
            "doctor_code": "D1", "birth_date": "1985-03-12"}
    base.update(kw)
    return AdmitPushRequest(**base)


@pytest.mark.asyncio
async def test_his_admit_no_weak_merge_same_name_birthdate(async_db):
    """HIS 链路：同名同生日但无强键 → 建两份档案，绝不误合并。"""
    doc = User(username="D1", password_hash="x", real_name="医生",
               role="doctor", employee_no="D1")
    async_db.add(doc)
    await async_db.commit()

    r1 = await process_admit(async_db, _admit(visit_id="V1"))
    r2 = await process_admit(async_db, _admit(visit_id="V2"))
    # 不同就诊、同名同生日、无身份证 → 必须是两份不同档案
    assert r1.patient_id != r2.patient_id
