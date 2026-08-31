# -*- coding: utf-8 -*-
"""质控统计与工作日日历测试（2026-08-21 阶段5）。"""
from datetime import date, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.medical_record import QCReport
from app.models.patient import Patient
from app.models.user import Department, User
from app.services.medical_record_service import MedicalRecordService
from app.services.workdays import add_workdays, is_workday


# ─── 工作日日历 ────────────────────────────────────────────────────

def test_workday_calendar_semantics():
    assert is_workday(date(2026, 8, 21)) is True      # 周五
    assert is_workday(date(2026, 8, 22)) is False     # 周六
    assert is_workday(date(2026, 10, 1)) is False     # 国庆
    assert is_workday(date(2026, 10, 10)) is True     # 调休上班的周六
    # 跨国庆的 7 个工作日：9-28(一)起 7 个工作日 = 9-29,30 + 10-8,9,10(调休),12,13
    dl = add_workdays(datetime(2026, 9, 28, 10, 0), 7)
    assert dl == datetime(2026, 10, 13, 10, 0), f"跨长假计算错误：{dl}"


# ─── 统计口径 ──────────────────────────────────────────────────────

def _user(role: str = "qc_officer"):
    return User(id=f"u-{role}", username=f"u_{role}", password_hash="x",
                real_name="测试", role=role, is_active=True)


@pytest.mark.asyncio
async def test_summary_latest_only_and_top_rules(async_db):
    """同文书多次评分只算最新一次；扣分条款 Top 从最新报告统计。"""
    async_db.add(Department(id="d1", name="骨伤科", code="GS"))
    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(id="e1", patient_id="p1", doctor_id="doc",
                           visit_type="inpatient", status="in_progress",
                           visited_at=datetime(2026, 8, 20), department_id="d1"))
    await async_db.flush()
    # 同一文书两次评分：旧 70（含条款X），新 95 甲级（含条款Y）——统计只认新
    async_db.add(QCReport(encounter_id="e1", record_type="admission_note",
                          rubric_key="zj_inpatient_2021", score=70, grade="丙级",
                          passed=False, department_id="d1", doctor_id="doc",
                          deductions=[{"rule_code": "IP-OLD-X", "description": "旧"}],
                          created_at=datetime(2026, 8, 20, 10, 0)))
    async_db.add(QCReport(encounter_id="e1", record_type="admission_note",
                          rubric_key="zj_inpatient_2021", score=95, grade="甲级",
                          passed=True, department_id="d1", doctor_id="doc",
                          deductions=[{"rule_code": "IP-NEW-Y", "description": "新"}],
                          created_at=datetime(2026, 8, 20, 12, 0)))
    await async_db.commit()

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: _user()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/api/v1/qc/stats/summary?days=30")
            d = r.json()
        dept = d["dept_stats"][0]
        assert dept["department"] == "骨伤科"
        assert dept["count"] == 1, "同文书多次评分必须只算最新一次"
        assert dept["avg_score"] == 95.0 and dept["grade_a_rate"] == 100.0
        codes = {t["rule_code"] for t in d["top_rules"]}
        assert codes == {"IP-NEW-Y"}, "旧报告的条款不得进 Top 统计"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_archive_proxy_caliber(async_db):
    """归档代理口径：全部签发且最晚签发≤出院后7工作日→达标；在途不入分母。"""
    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    # 甲：出院已 10 天前、全部签发在出院次日 → 达标
    async_db.add(Encounter(id="ok", patient_id="p1", doctor_id="doc",
                           visit_type="inpatient", status="completed",
                           visited_at=datetime(2026, 8, 1),
                           completed_at=datetime(2026, 8, 10, 9, 0)))
    # 乙：刚出院 1 小时、还有草稿 → 时限未到不入分母
    async_db.add(Encounter(id="pending", patient_id="p1", doctor_id="doc",
                           visit_type="inpatient", status="completed",
                           visited_at=datetime(2026, 8, 18),
                           completed_at=datetime.now()))
    await async_db.flush()
    svc = MedicalRecordService(async_db)
    # 必需三件套全部签发，这本病历才算齐（2026-08-31 齐套性修复 S2）：
    # 原夹具只签一份出院记录，按现实标准那本病历根本不齐——旧口径算的是
    # "建了的那几份都签了"，所以它能过。现在缺一件即不达标。
    for _rt, _c in (
        ("admission_note", "【主诉】胸闷 3 天"),
        ("first_course_record", "【病例特点】中年男性，急性起病"),
        ("discharge_record", "【出院诊断】冠心病，好转"),
    ):
        _r = await svc.quick_save(encounter_id="ok", record_type=_rt,
                                  content=_c, doctor_id="doc")
        # 手动把签发时间放到出院次日（quick_save 用 now）
        _r.submitted_at = datetime(2026, 8, 11, 9, 0)
    rec = _r
    await svc.auto_save_draft("pending", "discharge_record", "草稿", "doc")
    await async_db.commit()

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: _user()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/api/v1/qc/stats/summary?days=30")
            ap = r.json()["archive_proxy"]
        assert ap["total"] == 1 and ap["ok"] == 1, f"口径失真：{ap}"
        assert ap["rate"] == 100.0
        assert "代理口径" in ap["caliber"], "界面必须明示代理口径，不冒充真归档指标"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_export_csv_has_bom_and_sections(async_db):
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: _user()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/api/v1/qc/stats/export?days=30")
        assert r.status_code == 200
        body = r.content.decode("utf-8")
        assert body.startswith("﻿"), "缺 BOM，Excel 打开中文会乱码"
        assert "高频扣分条款" in body and "归档时效" in body
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_archive_counts_zero_doc_and_missing_required(async_db):
    """S1+S2 回归锁（2026-08-31 整本病历产物链审计）。

    S1：出院很久却**一份文书都没写**——病案不齐的最坏形态，原实现
        `if not recs: continue` 让它既不进分子也不进分母，指标对最该
        报警的病例完全免疫。时限已过必须计入分母且判不达标。
    S2：只签出院记录、入院记录与首程一份没建——原实现照样算达标。
    """
    async_db.add(Patient(id="p2", name="李四", birth_date=date(1965, 1, 1)))
    async_db.add(Encounter(id="empty", patient_id="p2", doctor_id="doc",
                           visit_type="inpatient", status="completed",
                           visited_at=datetime(2026, 7, 1),
                           completed_at=datetime(2026, 7, 20, 9, 0)))
    async_db.add(Encounter(id="partial", patient_id="p2", doctor_id="doc",
                           visit_type="inpatient", status="completed",
                           visited_at=datetime(2026, 7, 2),
                           completed_at=datetime(2026, 7, 21, 9, 0)))
    await async_db.flush()
    svc = MedicalRecordService(async_db)
    _p = await svc.quick_save(encounter_id="partial", record_type="discharge_record",
                              content="【出院诊断】愈", doctor_id="doc")
    _p.submitted_at = datetime(2026, 7, 22, 9, 0)
    await async_db.commit()

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: _user()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get("/api/v1/qc/stats/summary?days=90")
            ap = r.json()["archive_proxy"]
        assert ap["total"] >= 2, f"零文书/缺件的出院病历必须进分母：{ap}"
        assert ap["ok"] == 0, f"零文书与缺必需件都不该算达标：{ap}"
    finally:
        app.dependency_overrides.clear()
