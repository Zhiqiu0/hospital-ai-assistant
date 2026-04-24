"""住院服务（services/inpatient_service.py）测试

重点回归：list_active_ward 必须返回每条接诊的 age（由 birth_date 实时算）。
历史 bug：曾误用了不存在的 Patient.age 属性，导致 GET /inpatient/ward 直接 500。
本用例用真实 SQLite 内存库 + ORM 数据，避免 mock 掩盖字段错配。
"""
from datetime import date, datetime

import pytest

from app.models.encounter import Encounter
from app.models.patient import Patient
from app.services import inpatient_service


@pytest.mark.asyncio
async def test_list_active_ward_returns_inpatient_with_calculated_age(async_db):
    # 造一个住院中的患者：1990-01-01 生 → 当前应在 30+ 岁
    pat = Patient(
        id="pat-ward-1",
        name="测试住院患者",
        gender="男",
        birth_date=date(1990, 1, 1),
    )
    enc = Encounter(
        id="enc-ward-1",
        patient_id=pat.id,
        doctor_id="doc-ward-1",
        visit_type="inpatient",
        status="in_progress",
        bed_no="A-101",
        admission_route="门诊",
        admission_condition="一般",
        chief_complaint_brief="发热 3 天",
        visited_at=datetime(2026, 4, 25, 10, 0, 0),
    )
    async_db.add_all([pat, enc])
    await async_db.commit()

    items = await inpatient_service.list_active_ward(async_db, "doc-ward-1")

    assert len(items) == 1
    item = items[0]
    assert item["encounter_id"] == "enc-ward-1"
    assert item["patient_name"] == "测试住院患者"
    assert item["bed_no"] == "A-101"
    # age 应该是计算出来的整数，不是 None、不抛 AttributeError
    assert isinstance(item["age"], int)
    assert item["age"] >= 30


@pytest.mark.asyncio
async def test_list_active_ward_excludes_outpatient_and_completed(async_db):
    # 造三条：1) 住院中 2) 门诊接诊 3) 已结诊住院
    pat = Patient(id="pat-mix", name="混合用例", birth_date=date(1985, 6, 15))
    async_db.add(pat)
    await async_db.flush()

    encs = [
        Encounter(
            id="enc-active",
            patient_id=pat.id,
            doctor_id="doc-mix",
            visit_type="inpatient",
            status="in_progress",
            visited_at=datetime(2026, 4, 25, 9, 0),
        ),
        Encounter(
            id="enc-outpatient",
            patient_id=pat.id,
            doctor_id="doc-mix",
            visit_type="outpatient",
            status="in_progress",
            visited_at=datetime(2026, 4, 25, 9, 30),
        ),
        Encounter(
            id="enc-done",
            patient_id=pat.id,
            doctor_id="doc-mix",
            visit_type="inpatient",
            status="completed",
            visited_at=datetime(2026, 4, 24, 9, 0),
        ),
    ]
    async_db.add_all(encs)
    await async_db.commit()

    items = await inpatient_service.list_active_ward(async_db, "doc-mix")

    assert {it["encounter_id"] for it in items} == {"enc-active"}


@pytest.mark.asyncio
async def test_list_active_ward_filters_by_doctor(async_db):
    # 同一住院患者，不属于本医生 → 不应返回
    pat = Patient(id="pat-other", name="他人接诊", birth_date=date(1970, 1, 1))
    enc = Encounter(
        id="enc-other-doctor",
        patient_id=pat.id,
        doctor_id="doc-other",
        visit_type="inpatient",
        status="in_progress",
        visited_at=datetime(2026, 4, 25, 8, 0),
    )
    async_db.add_all([pat, enc])
    await async_db.commit()

    items = await inpatient_service.list_active_ward(async_db, "doc-me")
    assert items == []


@pytest.mark.asyncio
async def test_list_active_ward_age_none_when_birth_date_missing(async_db):
    # birth_date 为 None 的历史档案不应让接口炸，age 字段允许为 None
    pat = Patient(id="pat-no-birth", name="无生日记录")
    enc = Encounter(
        id="enc-no-birth",
        patient_id=pat.id,
        doctor_id="doc-nb",
        visit_type="inpatient",
        status="in_progress",
        visited_at=datetime(2026, 4, 25, 7, 0),
    )
    async_db.add_all([pat, enc])
    await async_db.commit()

    items = await inpatient_service.list_active_ward(async_db, "doc-nb")
    assert len(items) == 1
    assert items[0]["age"] is None
