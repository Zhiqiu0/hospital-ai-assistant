"""管理端病历列表批量取正文的回归测试（2026-08-14 第七轮审计 #13）。

原实现在遍历本页每一行时各查一次「最新版本」——一页 100 条就是 100 次往返。
改成两步聚合后最容易出的错是**取错版本**（拿到 v1 而不是最新的 v3），
所以这里既锁查询次数，也锁"确实取到最新版本的正文"。
"""

import pytest
from sqlalchemy import event

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.user import Department, User
from app.services.admin_record_service import AdminRecordService


async def _seed(db, n_records: int, versions_each: int) -> None:
    dept = Department(id="d1", name="内科", code="NK")
    doctor = User(
        id="u1", username="doc1", real_name="张医生", role="doctor",
        password_hash="x", department_id="d1",
    )
    db.add_all([dept, doctor])
    await db.flush()

    for i in range(n_records):
        patient = Patient(id=f"p{i}", name=f"患者{i}", gender="男")
        encounter = Encounter(
            id=f"e{i}", patient_id=patient.id, doctor_id="u1",
            visit_type="outpatient", status="completed",
        )
        record = MedicalRecord(
            id=f"r{i}", encounter_id=encounter.id,
            record_type="outpatient", status="submitted",
        )
        db.add_all([patient, encounter, record])
        await db.flush()
        for v in range(1, versions_each + 1):
            db.add(RecordVersion(
                id=f"r{i}-v{v}", medical_record_id=record.id, version_no=v,
                content={"text": f"病历{i} 第{v}版正文"},
                source="doctor_signed", triggered_by="u1",
            ))
        await db.flush()


@pytest.mark.asyncio
async def test_取的是最新版本的正文(async_db):
    """每份病历 3 个版本，列表必须显示第 3 版。"""
    await _seed(async_db, n_records=3, versions_each=3)

    result = await AdminRecordService(async_db).list_all_records(page=1, page_size=20)

    assert result["total"] == 3
    for item in result["items"]:
        assert "第3版" in item["content"], f"取到的不是最新版本：{item['content']}"


@pytest.mark.asyncio
async def test_查询次数不随行数增长(async_db):
    """核心不变量：这是本次修复要消掉的 N+1。"""
    await _seed(async_db, n_records=12, versions_each=2)

    counter = {"n": 0}

    def _count(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            counter["n"] += 1

    engine = async_db.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        result = await AdminRecordService(async_db).list_all_records(page=1, page_size=50)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert len(result["items"]) == 12
    # count + 主查询 + 版本号聚合 + 版本行 = 4；给 ORM 的零星查询留点余量。
    # 关键是它远小于「12 行各查一次」的 N+1 量级，且不随行数增长。
    assert counter["n"] <= 8, f"疑似仍是 N+1，实际 SELECT 次数={counter['n']}"


@pytest.mark.asyncio
async def test_没有任何版本的病历不炸(async_db):
    """病历行在、版本行还没落库的边界（签发过程中断）。"""
    await _seed(async_db, n_records=2, versions_each=0)

    result = await AdminRecordService(async_db).list_all_records(page=1, page_size=20)

    assert result["total"] == 2
    assert all(item["content"] == "" for item in result["items"])
