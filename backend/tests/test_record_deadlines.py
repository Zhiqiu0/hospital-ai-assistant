# -*- coding: utf-8 -*-
"""住院文书时限收口测试（2026-08-21 阶段0）。

验证：
  1. 时限唯一真相源生效——工作台 compliance 接口出现出院记录规则（此前缺失，
     与后台统计口径漂移）
  2. 出院记录起算点 = 出院时刻（completed_at）；未办出院时整条不显示，
     绝不按 now() 兜底（否则住院中的病人恒显超时）
  3. 已办出院后按出院时刻正确计算倒计时/超时
"""
from datetime import datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User
from app.services.record_deadlines import DEADLINE_HOURS, RECORD_DEADLINES


def test_deadline_single_source_covers_discharge():
    """唯一真相源必须含出院记录 24h（收口的核心目的）。"""
    assert DEADLINE_HOURS.get("discharge_record") == 24
    by_type = {r["record_type"]: r for r in RECORD_DEADLINES}
    assert by_type["discharge_record"]["start_field"] == "completed_at"
    assert by_type["admission_note"]["start_field"] == "visited_at"


async def _get_compliance(async_db, enc, doc):
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: doc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.get(f"/api/v1/encounters/{enc.id}/compliance")
        assert res.status_code == 200
        return {i["record_type"]: i for i in res.json()["items"]}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_discharge_deadline_hidden_before_discharge(async_db):
    """未办出院（completed_at 为空）时出院记录不显示倒计时——不能按 now 兜底。"""
    doc = User(username="DL1", password_hash="x", real_name="医生", role="doctor")
    pat = Patient(name="时效患者甲")
    async_db.add_all([doc, pat])
    await async_db.flush()
    enc = Encounter(
        patient_id=pat.id, doctor_id=doc.id, visit_type="inpatient",
        status="in_progress", visited_at=datetime.now() - timedelta(days=15),
    )
    async_db.add(enc)
    await async_db.commit()

    items = await _get_compliance(async_db, enc, doc)
    # 入院记录/首程正常显示（住院 15 天早已超时）
    assert items["admission_note"]["status"] == "overdue"
    # 出院记录整条不出现——住院 15 天的病人若按 now/入院兜底会"永久超时"
    assert "discharge_record" not in items


@pytest.mark.asyncio
async def test_discharge_deadline_counts_from_completed_at(async_db):
    """已办出院后，出院记录按出院时刻起算 24h 倒计时。"""
    doc = User(username="DL2", password_hash="x", real_name="医生", role="doctor")
    pat = Patient(name="时效患者乙")
    async_db.add_all([doc, pat])
    await async_db.flush()
    enc = Encounter(
        patient_id=pat.id, doctor_id=doc.id, visit_type="inpatient",
        status="completed", visited_at=datetime.now() - timedelta(days=15),
        # 2 小时前办的出院 → 剩余约 22 小时，状态应为 ok 而非超时
        completed_at=datetime.now() - timedelta(hours=2),
    )
    async_db.add(enc)
    await async_db.commit()

    items = await _get_compliance(async_db, enc, doc)
    dis = items.get("discharge_record")
    assert dis is not None, "出院后应显示出院记录时效卡"
    assert dis["status"] == "ok", f"按出院时刻起算应剩约22h，实际 status={dis['status']}"
