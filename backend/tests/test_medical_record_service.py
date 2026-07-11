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


@pytest.mark.asyncio
async def test_auto_save_draft_tolerates_aware_expected_updated_at(async_db, draft_record):
    """乐观锁比较：前端回传带时区(aware)的 expected_updated_at 不再触发 TypeError 500。

    DB updated_at 是 naive，若直接与 aware 值比较会抛 TypeError → auto-save 500。
    修复后先归一化，正常返回（不冲突时应成功保存）。
    """
    from datetime import timezone

    svc = MedicalRecordService(async_db)
    # 用一个很早的 aware 时间作为预期值：DB 里的 updated_at 会更新 → 不应误判冲突崩溃，
    # 而应正常按乐观锁语义处理（这里预期值远早于现在，理论上会判 409，但关键是不 TypeError）
    early_aware = draft_record.updated_at.replace(tzinfo=timezone.utc) if draft_record.updated_at else None
    # 传一个「等于当前」的 aware 值，确保不冲突、能正常保存
    result = await svc.auto_save_draft(
        encounter_id=draft_record.encounter_id,
        record_type="outpatient",
        content="草稿内容",
        user_id="doc-001",
        expected_updated_at=early_aware,
    )
    # 关键断言：没有抛 TypeError，正常返回字典
    assert "version_no" in result
