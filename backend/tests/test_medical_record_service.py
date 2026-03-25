"""
病历服务单元测试
- 已签发病历不可再修改（后端锁）
- 版本号在每次保存时递增
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from app.models.medical_record import MedicalRecord
from app.models.encounter import Encounter
from app.schemas.medical_record import RecordContentUpdate
from app.services.medical_record_service import MedicalRecordService


@pytest_asyncio.fixture
async def draft_record(async_db):
    enc = Encounter(
        patient_id="pat-001",
        doctor_id="doc-001",
        visit_type="outpatient",
    )
    async_db.add(enc)
    await async_db.flush()

    record = MedicalRecord(
        encounter_id=enc.id,
        record_type="outpatient",
        status="draft",
        current_version=0,
    )
    async_db.add(record)
    await async_db.commit()
    return record


@pytest_asyncio.fixture
async def submitted_record(async_db):
    enc = Encounter(
        patient_id="pat-002",
        doctor_id="doc-001",
        visit_type="outpatient",
    )
    async_db.add(enc)
    await async_db.flush()

    record = MedicalRecord(
        encounter_id=enc.id,
        record_type="outpatient",
        status="submitted",
        current_version=3,
    )
    async_db.add(record)
    await async_db.commit()
    return record


@pytest.mark.asyncio
async def test_save_content_increments_version(async_db, draft_record):
    svc = MedicalRecordService(async_db)
    data = RecordContentUpdate(content={"text": "新内容"})
    result = await svc.save_content(draft_record.id, data, "doc-001")
    assert result["version_no"] == 1


@pytest.mark.asyncio
async def test_save_content_twice_increments_version_twice(async_db, draft_record):
    svc = MedicalRecordService(async_db)
    data = RecordContentUpdate(content={"text": "第一次"})
    await svc.save_content(draft_record.id, data, "doc-001")
    data2 = RecordContentUpdate(content={"text": "第二次"})
    result = await svc.save_content(draft_record.id, data2, "doc-001")
    assert result["version_no"] == 2


@pytest.mark.asyncio
async def test_submitted_record_cannot_be_edited(async_db, submitted_record):
    """已签发病历后端应拒绝修改，返回 403"""
    svc = MedicalRecordService(async_db)
    data = RecordContentUpdate(content={"text": "尝试修改"})
    with pytest.raises(HTTPException) as exc_info:
        await svc.save_content(submitted_record.id, data, "doc-001")
    assert exc_info.value.status_code == 403
