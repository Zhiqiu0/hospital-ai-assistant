# -*- coding: utf-8 -*-
"""医生端"质控退回提醒"测试（2026-08-22 退回闭环）。

覆盖 GET /medical-records/my-returned 的完整口径：
  - 被退回的文书出现在本医生清单里，且带复核意见/复核人
  - 复核通过的文书不出现
  - 退回后医生修订重签 → 自动出清单（与复核队列"重签需再核"互为镜像）
  - 别的医生被退回的文书不可见（归属隔离）
  - 静态路径不被动态段 /{record_id} 吞掉（路由顺序回归锚点）
"""
from datetime import date, datetime, timedelta
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.medical_record import QCReview
from app.models.patient import Patient
from app.models.user import User
from app.services.medical_record_service import MedicalRecordService


def _user(uid: str, role: str = "doctor"):
    return User(id=uid, username=f"u_{uid}", password_hash="x",
                real_name=f"用户{uid}", role=role, is_active=True)


@pytest_asyncio.fixture
async def seeded(async_db):
    """两位医生各一份已签发文书；由质控员分别给出退回/通过结论。"""
    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-me", visit_type="inpatient",
        status="in_progress", visited_at=datetime(2026, 8, 22),
    ))
    async_db.add(Encounter(
        id="enc-2", patient_id="p1", doctor_id="doc-other", visit_type="inpatient",
        status="in_progress", visited_at=datetime(2026, 8, 22),
    ))
    await async_db.flush()
    svc = MedicalRecordService(async_db)
    mine = await svc.quick_save(encounter_id="enc-1", record_type="admission_note",
                                content="【主诉】\n发热", doctor_id="doc-me")
    other = await svc.quick_save(encounter_id="enc-2", record_type="admission_note",
                                 content="【主诉】\n咳嗽", doctor_id="doc-other")
    # 复核时间显式取"签发后 1ms/2ms"：真实世界复核晚于签发是秒级间隔，
    # 测试里若靠 datetime.now 默认值，同一时钟刻度可能与签发/彼此平票
    # （Windows 时钟颗粒度，实测偶发），显式偏移彻底消除 flaky
    return {"mine": mine.id, "other": other.id,
            "t_mine": mine.submitted_at, "t_other": other.submitted_at}


def _client_as(async_db, user) -> AsyncClient:
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def _review(record_id: str, encounter_id: str, conclusion: str,
            comment: str | None = None, at: datetime | None = None):
    """直接落一条复核记录（提交端点已有专门测试，这里只测清单口径）。

    at：显式复核时间。留空用默认 datetime.now——但涉及先后序比较的用例
    必须显式传，避免时钟颗粒度平票（见 seeded 注释）。
    """
    return QCReview(medical_record_id=record_id, encounter_id=encounter_id,
                    reviewer_id="qa-1", reviewer_name="钱质控",
                    conclusion=conclusion, comment=comment, created_at=at)


@pytest.mark.asyncio
async def test_returned_visible_with_comment_and_isolation(async_db, seeded):
    """本人被退回可见（含意见）；他人被退回不可见；通过结论不出现。"""
    async_db.add(_review(seeded["mine"], "enc-1", "returned", "主诉缺持续时间，请补充",
                         at=seeded["t_mine"] + timedelta(milliseconds=1)))
    async_db.add(_review(seeded["other"], "enc-2", "returned", "别人的退回",
                         at=seeded["t_other"] + timedelta(milliseconds=1)))
    await async_db.commit()

    async with _client_as(async_db, _user("doc-me")) as ac:
        r = await ac.get("/api/v1/medical-records/my-returned")
        assert r.status_code == 200, r.text
        items = r.json()
        assert len(items) == 1, "只见自己的退回"
        it = items[0]
        assert it["record_id"] == seeded["mine"]
        assert it["comment"] == "主诉缺持续时间，请补充"
        assert it["reviewer_name"] == "钱质控"
        assert it["visit_type"] == "inpatient"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_passed_review_not_listed(async_db, seeded):
    """最新结论为通过 → 不在整改清单（含"先退回后通过"的覆盖场景）。"""
    async_db.add(_review(seeded["mine"], "enc-1", "returned", "先退一次",
                         at=seeded["t_mine"] + timedelta(milliseconds=1)))
    async_db.add(_review(seeded["mine"], "enc-1", "passed",
                         at=seeded["t_mine"] + timedelta(milliseconds=2)))
    await async_db.commit()

    async with _client_as(async_db, _user("doc-me")) as ac:
        r = await ac.get("/api/v1/medical-records/my-returned")
        assert r.json() == [], "最新结论已通过，不该再提醒整改"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_resign_clears_reminder(async_db, seeded):
    """医生修订重签（submitted_at 晚于复核时间）→ 提醒自动消失。"""
    async_db.add(_review(seeded["mine"], "enc-1", "returned", "请修订",
                         at=seeded["t_mine"] + timedelta(milliseconds=1)))
    await async_db.commit()

    async with _client_as(async_db, _user("doc-me")) as ac:
        r = await ac.get("/api/v1/medical-records/my-returned")
        assert len(r.json()) == 1
    app.dependency_overrides.clear()

    # 医生整改后重签：quick_save 覆盖更新 submitted_at → 出清单
    svc = MedicalRecordService(async_db)
    await svc.quick_save(encounter_id="enc-1", record_type="admission_note",
                         content="【主诉】\n发热3天（已修订）", doctor_id="doc-me")

    async with _client_as(async_db, _user("doc-me")) as ac:
        r = await ac.get("/api/v1/medical-records/my-returned")
        assert r.json() == [], "重签后应自动出清单（重新进入复核队列由队列侧保证）"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_route_not_swallowed_by_dynamic_segment(async_db, seeded):
    """回归锚点：/my-returned 必须先于 /{record_id} 注册，否则会被当作
    record_id 查库返回 404（本次开发中真实踩过的坑）。"""
    async with _client_as(async_db, _user("doc-me")) as ac:
        r = await ac.get("/api/v1/medical-records/my-returned")
        assert r.status_code == 200, "静态路径被动态段吞掉会 404/422"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_revise_clears_reminder_and_requeues(async_db, seeded):
    """门急诊整改通道 = 管理员修订（2026-08-28 口径对拍修复）：
    修订只建 RecordVersion(source=admin_revise) 不动 submitted_at——
    ①医生退回横幅必须消失 ②文书必须重新进入复核队列。"""
    from app.models.medical_record import RecordVersion

    async_db.add(_review(seeded["mine"], "enc-1", "returned", "门诊退回",
                         at=seeded["t_mine"] + timedelta(milliseconds=1)))
    await async_db.commit()

    async with _client_as(async_db, _user("doc-me")) as ac:
        assert len((await ac.get("/api/v1/medical-records/my-returned")).json()) == 1
    app.dependency_overrides.clear()

    # 管理员修订：新版本 source=admin_revise，时间晚于退回
    async_db.add(RecordVersion(
        medical_record_id=seeded["mine"], version_no=99,
        content={"text": "修订后的正文"}, source="admin_revise",
        created_at=seeded["t_mine"] + timedelta(milliseconds=5)))
    await async_db.commit()

    async with _client_as(async_db, _user("doc-me")) as ac:
        assert (await ac.get("/api/v1/medical-records/my-returned")).json() == [], \
            "管理员修订后退回横幅必须消失"
    app.dependency_overrides.clear()

    # 复核队列侧：修订晚于最新复核 → 重新入队
    async with _client_as(async_db, _user("qh", "qc_officer")) as ac:
        ids = {i["record_id"] for i in
               (await ac.get("/api/v1/qc/review-queue")).json()["items"]}
        assert seeded["mine"] in ids, "管理员修订后必须重新进入复核队列"
    app.dependency_overrides.clear()
