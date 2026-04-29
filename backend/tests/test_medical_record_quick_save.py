"""
medical_record_service.quick_save 测试（M5）

覆盖范围：
  - 首次签发（病历记录尚未创建）→ 自动新建并写入版本 1
  - 重复签发同 encounter+record_type → version 递增不重复创建
  - 内容存储格式：{"text": content}
  - 状态联动：
      - 门诊/急诊：encounter.status → completed
      - 住院：encounter.status 保持 in_progress（多份病历，签发≠出院）
  - 审计字段：record.submitted_at 写入、version.triggered_by = doctor_id
  - 权限/越权由路由层负责，本 service 测试不再覆盖

工程注意：
  redis_cache 失效调用对本地 Redis 真删 key，本测试只关注 DB 状态，
  通过 monkeypatch 把 invalidate_* 改成 no-op，避免依赖外部服务。
"""
from datetime import datetime

import pytest
import pytest_asyncio

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.services.medical_record_service import MedicalRecordService


@pytest.fixture(autouse=True)
def disable_cache_invalidation(monkeypatch):
    """避免测试依赖本地 Redis：缓存失效调用全部 no-op。"""
    from app.services import encounter_service

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(encounter_service, "invalidate_encounter_snapshot", _noop)
    monkeypatch.setattr(encounter_service, "invalidate_my_encounters", _noop)


async def _make_encounter(async_db, *, encounter_id: str, visit_type: str = "outpatient") -> Encounter:
    """构造一条 in_progress 接诊（含必需的 patient FK）。"""
    pat_id = f"pat-{encounter_id}"
    pat = Patient(id=pat_id, name=f"患者-{encounter_id}")
    enc = Encounter(
        id=encounter_id,
        patient_id=pat_id,
        doctor_id="doc-qs-1",
        visit_type=visit_type,
        status="in_progress",
        is_first_visit=True,
        visited_at=datetime(2026, 4, 28, 9, 0, 0),
    )
    async_db.add_all([pat, enc])
    await async_db.commit()
    return enc


# ── 首次签发：创建 record + version 1 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_quick_save_creates_record_when_missing(async_db):
    """病历不存在时（医生跳过 AI 生成直接签发），quick_save 应自动创建 record + version 1。"""
    enc = await _make_encounter(async_db, encounter_id="enc-qs-new")
    svc = MedicalRecordService(async_db)

    record = await svc.quick_save(
        encounter_id=enc.id,
        record_type="outpatient",
        content="首次签发的病历正文",
        doctor_id="doc-qs-1",
    )

    assert record.encounter_id == enc.id
    assert record.record_type == "outpatient"
    assert record.status == "submitted"
    assert record.current_version == 1
    assert record.submitted_at is not None


# ── 二次签发：version 递增 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quick_save_increments_version_when_record_exists(async_db):
    """已有 draft 病历（current_version=2）再签发，version 应递增到 3。"""
    enc = await _make_encounter(async_db, encounter_id="enc-qs-exist")
    pre = MedicalRecord(
        id="rec-pre-1",
        encounter_id=enc.id,
        record_type="outpatient",
        status="draft",
        current_version=2,
    )
    async_db.add(pre)
    await async_db.commit()

    svc = MedicalRecordService(async_db)
    record = await svc.quick_save(
        encounter_id=enc.id,
        record_type="outpatient",
        content="签发版本",
        doctor_id="doc-qs-1",
    )

    assert record.id == "rec-pre-1"  # 复用已有 record
    assert record.current_version == 3
    assert record.status == "submitted"


# ── 内容格式：{"text": content} ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quick_save_stores_content_as_text_dict(async_db):
    """quick_save 必须以 {"text": content} 格式存版本（与读路径 _parse_record_content 对齐）。"""
    enc = await _make_encounter(async_db, encounter_id="enc-qs-fmt")
    svc = MedicalRecordService(async_db)

    record = await svc.quick_save(
        encounter_id=enc.id,
        record_type="outpatient",
        content="病历内容XYZ",
        doctor_id="doc-qs-1",
    )

    from sqlalchemy import select
    version = (await async_db.execute(
        select(RecordVersion).where(
            RecordVersion.medical_record_id == record.id,
            RecordVersion.version_no == record.current_version,
        )
    )).scalar_one()

    assert version.content == {"text": "病历内容XYZ"}
    assert version.source == "doctor_signed"
    assert version.triggered_by == "doc-qs-1"


# ── 接诊状态联动 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quick_save_outpatient_closes_encounter(async_db):
    """门诊签发应关闭接诊（status → completed）。"""
    enc = await _make_encounter(async_db, encounter_id="enc-qs-out", visit_type="outpatient")
    svc = MedicalRecordService(async_db)
    await svc.quick_save(
        encounter_id=enc.id,
        record_type="outpatient",
        content="门诊签发",
        doctor_id="doc-qs-1",
    )

    await async_db.refresh(enc)
    assert enc.status == "completed"


@pytest.mark.asyncio
async def test_quick_save_emergency_closes_encounter(async_db):
    """急诊签发也应关闭接诊（与门诊一致）。"""
    enc = await _make_encounter(async_db, encounter_id="enc-qs-er", visit_type="emergency")
    svc = MedicalRecordService(async_db)
    await svc.quick_save(
        encounter_id=enc.id,
        record_type="emergency",
        content="急诊处理记录",
        doctor_id="doc-qs-1",
    )

    await async_db.refresh(enc)
    assert enc.status == "completed"


@pytest.mark.asyncio
async def test_quick_save_inpatient_keeps_encounter_open(async_db):
    """住院签发不能关闭接诊：一次住院有多份病历（入院/病程/出院），
    签发任一份都不代表出院。
    """
    enc = await _make_encounter(async_db, encounter_id="enc-qs-in", visit_type="inpatient")
    svc = MedicalRecordService(async_db)
    await svc.quick_save(
        encounter_id=enc.id,
        record_type="admission_note",
        content="入院记录",
        doctor_id="doc-qs-1",
    )

    await async_db.refresh(enc)
    assert enc.status == "in_progress"  # 关键：保持开放


# ── 跨表事务：encounter + medical_record + record_version 一起提交 ─────────


@pytest.mark.asyncio
async def test_quick_save_commits_all_three_tables_atomically(async_db):
    """门诊签发后应观察到：record / version / encounter status 三张表同时更新。"""
    enc = await _make_encounter(async_db, encounter_id="enc-qs-atomic")
    svc = MedicalRecordService(async_db)
    record = await svc.quick_save(
        encounter_id=enc.id,
        record_type="outpatient",
        content="原子提交测试",
        doctor_id="doc-qs-1",
    )

    from sqlalchemy import select
    # 1) MedicalRecord 已写入
    db_record = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.id == record.id)
    )).scalar_one()
    assert db_record.status == "submitted"
    assert db_record.submitted_at is not None

    # 2) RecordVersion 已写入
    db_version = (await async_db.execute(
        select(RecordVersion).where(RecordVersion.medical_record_id == record.id)
    )).scalar_one()
    assert db_version.version_no == 1
    assert db_version.content == {"text": "原子提交测试"}

    # 3) Encounter 状态已更新
    db_enc = (await async_db.execute(
        select(Encounter).where(Encounter.id == enc.id)
    )).scalar_one()
    assert db_enc.status == "completed"


# ── 同接诊+不同类型：可以独立签发 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_quick_save_different_record_types_create_separate_records(async_db):
    """住院场景下，同一 encounter 不同 record_type 应独立创建病历，互不影响。"""
    enc = await _make_encounter(async_db, encounter_id="enc-qs-multi", visit_type="inpatient")
    svc = MedicalRecordService(async_db)

    rec_admission = await svc.quick_save(
        encounter_id=enc.id,
        record_type="admission_note",
        content="入院记录",
        doctor_id="doc-qs-1",
    )
    rec_course = await svc.quick_save(
        encounter_id=enc.id,
        record_type="course_record",
        content="日常病程",
        doctor_id="doc-qs-1",
    )

    assert rec_admission.id != rec_course.id
    assert rec_admission.record_type == "admission_note"
    assert rec_course.record_type == "course_record"
    # 接诊保持 in_progress（住院不因签发任一病历而关闭）
    await async_db.refresh(enc)
    assert enc.status == "in_progress"
