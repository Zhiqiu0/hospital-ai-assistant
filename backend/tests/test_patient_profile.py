"""
患者档案单元测试（services/patient_service 的 get_profile / update_profile）

核心验证：
  - 新建患者 profile 全空
  - update_profile 只覆盖传入字段，已有数据保留
  - update_profile 会更新 profile_updated_at
  - 不存在的患者返回 404
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from app.models.patient import Patient
from app.schemas.patient import PatientProfileUpdate
from app.services.patient_service import PatientService


@pytest_asyncio.fixture
async def patient(async_db):
    p = Patient(name="张三", gender="male")
    async_db.add(p)
    await async_db.commit()
    return p


@pytest.mark.asyncio
async def test_new_patient_has_empty_profile(async_db, patient):
    svc = PatientService(async_db)
    profile = await svc.get_profile(patient.id)
    assert profile["allergy_history"] is None
    assert profile["past_history"] is None
    assert profile["updated_at"] is None


@pytest.mark.asyncio
async def test_update_profile_sets_fields_and_timestamp(async_db, patient):
    svc = PatientService(async_db)
    result = await svc.update_profile(
        patient.id,
        PatientProfileUpdate(allergy_history="青霉素", past_history="高血压"),
    )
    assert result["allergy_history"] == "青霉素"
    assert result["past_history"] == "高血压"
    assert result["updated_at"] is not None


@pytest.mark.asyncio
async def test_update_profile_partial_does_not_overwrite_other_fields(async_db, patient):
    """只传 allergy_history 时，past_history 不应被置空。"""
    svc = PatientService(async_db)
    await svc.update_profile(
        patient.id,
        PatientProfileUpdate(allergy_history="青霉素", past_history="高血压"),
    )
    # 再次更新，只传 allergy_history
    result = await svc.update_profile(
        patient.id,
        PatientProfileUpdate(allergy_history="青霉素, 花粉"),
    )
    assert result["allergy_history"] == "青霉素, 花粉"
    assert result["past_history"] == "高血压"  # 保留


@pytest.mark.asyncio
async def test_update_profile_on_missing_patient_raises_404(async_db):
    svc = PatientService(async_db)
    with pytest.raises(HTTPException) as exc_info:
        await svc.update_profile(
            "non-existent-id",
            PatientProfileUpdate(allergy_history="青霉素"),
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_profile_on_missing_patient_raises_404(async_db):
    svc = PatientService(async_db)
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_profile("non-existent-id")
    assert exc_info.value.status_code == 404
