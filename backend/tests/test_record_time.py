"""补记判定（2026-08-14 第八轮审计后按行业标准新增）。

依据：医法实务（AHIMA 等）明确要求——补记应带当前日期、**明确标注为补记**、
原记录保持可见；绝不允许静默回填过去时间。电子病历有审计轨迹，事后改时间线
一查即知，未标注的补记在医疗纠纷中会被当作可疑证据。

本项目的取舍：**不阻止**医生记录较早的诊疗时点（住院补写前一天的病程是正当
且必要的），但**一定标出来**。
"""

from datetime import datetime, timedelta

import pytest

from app.services.record_time import describe_record_time, is_late_entry


def test_当场书写不算补记():
    now = datetime(2026, 8, 5, 10, 0)
    assert is_late_entry(now, now) is False


def test_夜班晚几小时记录当天查房不算补记():
    """23:50 记录当天 20:00 的查房属正常书写，不该被扣上补记的帽子。"""
    recorded = datetime(2026, 8, 5, 20, 0)
    entered = datetime(2026, 8, 5, 23, 50)
    assert is_late_entry(recorded, entered) is False


def test_隔天补写判为补记():
    recorded = datetime(2026, 8, 5, 10, 0)
    entered = datetime(2026, 8, 8, 9, 0)
    assert is_late_entry(recorded, entered) is True


def test_未填记录时间不算补记():
    """门急诊当场书写，本就不填 recorded_at。"""
    assert is_late_entry(None, datetime(2026, 8, 5, 10, 0)) is False


def test_补记时两个时间都要露出来():
    """规范要求「明确标注为补记、原记录保持可见」，前端得同时拿到两个时间。"""
    recorded = datetime(2026, 8, 5, 10, 0)
    entered = datetime(2026, 8, 8, 9, 0)

    info = describe_record_time(recorded, entered)

    assert info["is_late_entry"] is True
    assert info["recorded_at"] == "2026-08-05T10:00:00"
    assert info["entered_at"] == "2026-08-08T09:00:00"


@pytest.mark.parametrize("hours,expected", [(11, False), (12, True), (13, True)])
def test_阈值边界(hours, expected):
    recorded = datetime(2026, 8, 5, 8, 0)
    assert is_late_entry(recorded, recorded + timedelta(hours=hours)) is expected


# ── 端到端：记录时间要能存进病历并从快照里带出补记标识 ──────────────────────

@pytest.mark.asyncio
async def test_住院病程的记录时间落库并标出补记(async_db):
    """医生 8/8 补写 8/5 的病程 → 存下临床时点，且快照里标为补记。"""
    from datetime import date

    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord
    from app.models.patient import Patient
    from app.services.encounter_serializers import _serialize_record
    from app.services.medical_record_service import MedicalRecordService
    from sqlalchemy import select

    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-1",
        visit_type="inpatient", status="in_progress",
        visited_at=datetime(2026, 8, 1),
    ))
    await async_db.flush()

    svc = MedicalRecordService(async_db)
    await svc.auto_save_draft(
        "enc-1", "course_record", "8月5日的病程内容", "doc-1",
        recorded_at=datetime(2026, 8, 5, 10, 0),
    )

    rec = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.encounter_id == "enc-1")
    )).scalar_one()
    assert rec.recorded_at == datetime(2026, 8, 5, 10, 0)

    # created_at 由 DB 默认值给"现在"，与 8/5 相差远超阈值 → 补记
    payload = _serialize_record(rec, None)
    assert payload["recorded_at"] == "2026-08-05T10:00:00"
    assert payload["is_late_entry"] is True, "补记没有被标出来"
    assert payload["entered_at"], "系统录入时间必须一并给前端（原记录保持可见）"


@pytest.mark.asyncio
async def test_门诊不填记录时间不受影响(async_db):
    """门急诊当场书写，本就不用这个字段。"""
    from datetime import date

    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord
    from app.models.patient import Patient
    from app.services.encounter_serializers import _serialize_record
    from app.services.medical_record_service import MedicalRecordService
    from sqlalchemy import select

    async_db.add(Patient(id="p2", name="李四", birth_date=date(1980, 1, 1)))
    async_db.add(Encounter(
        id="enc-2", patient_id="p2", doctor_id="doc-1",
        visit_type="outpatient", status="in_progress",
        visited_at=datetime(2026, 8, 1),
    ))
    await async_db.flush()

    await MedicalRecordService(async_db).auto_save_draft(
        "enc-2", "outpatient", "门诊病历", "doc-1"
    )
    rec = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.encounter_id == "enc-2")
    )).scalar_one()

    payload = _serialize_record(rec, None)
    assert payload["recorded_at"] is None
    assert payload["is_late_entry"] is False
