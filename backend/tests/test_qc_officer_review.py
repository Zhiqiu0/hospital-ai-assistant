# -*- coding: utf-8 -*-
"""质控员复核工作台测试（2026-08-21 阶段4）。

覆盖：
  - 权限：doctor/nurse 403；qc_officer/admin 放行；科室质控员只见本科室
  - 队列口径：仅已签发；已复核消失；退回后医生重签 → 重新出现在队列
  - 复核提交：退回必填意见；落库 + 历史可查
  - 红线：qc_officer 不能写病历（assert_can_write_record 拒绝）
"""
from datetime import date, datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.authz import assert_can_write_record
from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User
from app.services.medical_record_service import MedicalRecordService


def _user(uid: str, role: str, dept: str | None = None):
    return User(id=uid, username=f"u_{uid}", password_hash="x", real_name=f"用户{uid}",
                role=role, is_active=True, department_id=dept)


@pytest_asyncio.fixture
async def seeded(async_db):
    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(
        id="enc-a", patient_id="p1", doctor_id="doc-1", visit_type="inpatient",
        status="in_progress", visited_at=datetime(2026, 8, 20), department_id="dept-A",
    ))
    async_db.add(Encounter(
        id="enc-b", patient_id="p1", doctor_id="doc-2", visit_type="inpatient",
        status="in_progress", visited_at=datetime(2026, 8, 20), department_id="dept-B",
    ))
    await async_db.flush()
    svc = MedicalRecordService(async_db)
    # 科室A：一份已签发 + 一份草稿；科室B：一份已签发
    a = await svc.quick_save(encounter_id="enc-a", record_type="admission_note",
                             content="【主诉】\n发热", doctor_id="doc-1")
    await svc.auto_save_draft("enc-a", "first_course_record", "草稿", "doc-1")
    b = await svc.quick_save(encounter_id="enc-b", record_type="admission_note",
                             content="【主诉】\n咳嗽", doctor_id="doc-2")
    # quick_save 返回 ORM 对象
    return {"a": a.id, "b": b.id}


def _client_as(async_db, user) -> AsyncClient:
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_doctor_and_nurse_denied(async_db, seeded):
    for role in ("doctor", "nurse"):
        async with _client_as(async_db, _user(f"x-{role}", role)) as ac:
            r = await ac.get("/api/v1/qc/review-queue")
            assert r.status_code == 403, f"{role} 不该进质控通道"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dept_officer_sees_own_dept_only(async_db, seeded):
    """科室质控员只看本科室；院级（无科室）看全部。"""
    async with _client_as(async_db, _user("qa", "qc_officer", dept="dept-A")) as ac:
        r = await ac.get("/api/v1/qc/review-queue")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1 and items[0]["record_id"] == seeded["a"]
        assert all(i["record_type"] == "admission_note" for i in items), "草稿不得入队"
    async with _client_as(async_db, _user("qh", "qc_officer", dept=None)) as ac:
        r = await ac.get("/api/v1/qc/review-queue")
        assert {i["record_id"] for i in r.json()["items"]} == {seeded["a"], seeded["b"]}
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_review_flow_and_queue_semantics(async_db, seeded):
    """复核通过→出队；退回必填意见；退回后医生重签→重新入队。"""
    officer = _user("qa", "qc_officer", dept="dept-A")
    async with _client_as(async_db, officer) as ac:
        # 退回无意见 → 422
        r = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": seeded["a"], "conclusion": "returned"})
        assert r.status_code == 422
        # 复核通过 → 出队
        r = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": seeded["a"], "conclusion": "passed"})
        assert r.status_code == 200
        r = await ac.get("/api/v1/qc/review-queue")
        assert r.json()["items"] == []
        # 详情页能看到复核历史 + 全文
        r = await ac.get(f"/api/v1/qc/records/{seeded['a']}")
        d = r.json()
        assert d["reviews"][0]["conclusion"] == "passed"
        assert "发热" in d["content"]
        # 越科室详情 403
        r = await ac.get(f"/api/v1/qc/records/{seeded['b']}")
        assert r.status_code == 403
    # 医生修订重签（quick_save 覆盖更新 submitted_at）→ 重新入队
    svc = MedicalRecordService(async_db)
    await svc.quick_save(encounter_id="enc-a", record_type="admission_note",
                         content="【主诉】\n发热（修订）", doctor_id="doc-1")
    async with _client_as(async_db, officer) as ac:
        r = await ac.get("/api/v1/qc/review-queue")
        assert len(r.json()["items"]) == 1, "重签后需要再次复核"
    app.dependency_overrides.clear()


def test_qc_officer_cannot_write_records():
    """红线：质控员绝无病历书写权（署名必须是接诊医生本人）。"""
    with pytest.raises(HTTPException):
        assert_can_write_record(_user("q1", "qc_officer"))


@pytest.mark.asyncio
async def test_detail_rejects_draft_and_submit_idempotent(async_db, seeded):
    """2026-08-28 体检修复回归：①详情端点不得泄露未签发草稿全文；
    ②同结论同意见重复提交幂等不插行（防双击虚增通报指标）；
    ③意见超 2000 字被 422 拒收。"""
    from sqlalchemy import func as sa_func, select as sa_select
    from app.models.medical_record import QCReview
    from app.services.medical_record_service import MedicalRecordService

    officer = _user("qa", "qc_officer", dept="dept-A")
    # 造一份草稿（auto_save_draft 不签发）
    svc = MedicalRecordService(async_db)
    draft = await svc.auto_save_draft("enc-a", "course_record", "草稿内容勿泄", "doc-1")
    draft_id = draft["record_id"] if isinstance(draft, dict) else draft.id
    async with _client_as(async_db, officer) as ac:
        r = await ac.get(f"/api/v1/qc/records/{draft_id}")
        assert r.status_code == 404, "草稿必须 404，不得给质控员看未定稿全文"

        # 重复提交幂等：同结论+同意见 第二次不插行
        r1 = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": seeded["a"], "conclusion": "returned",
            "comment": "主诉需补充"})
        assert r1.status_code == 200 and not r1.json().get("duplicate")
        r2 = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": seeded["a"], "conclusion": "returned",
            "comment": "主诉需补充"})
        assert r2.json().get("duplicate") is True
        n = (await async_db.execute(
            sa_select(sa_func.count()).select_from(QCReview)
            .where(QCReview.medical_record_id == seeded["a"]))).scalar()
        assert n == 1, "重复提交不得插入第二行"
        # 同结论但意见不同 = 质控员补充意见，允许再插
        r3 = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": seeded["a"], "conclusion": "returned",
            "comment": "主诉需补充持续时间与诱因"})
        assert not r3.json().get("duplicate")

        # 意见超长 422
        r4 = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": seeded["a"], "conclusion": "returned",
            "comment": "长" * 2001})
        assert r4.status_code == 422
    app.dependency_overrides.clear()
