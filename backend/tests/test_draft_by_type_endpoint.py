# -*- coding: utf-8 -*-
"""GET /medical-records/draft-by-type 端点测试（2026-08-21 第四轮走查）。

背景：住院切文书类型时前端只认本地缓存，服务端有该类型草稿却显示空编辑器。
本端点按 (encounter, record_type) 返回最新一份的内容/状态/updated_at。

覆盖：
  - 有草稿 → exists=True + 内容 + updated_at（前端同步 auto-save 基线用）
  - 没写过该类型 → exists=False（200，不产生 console 404 噪音）
  - 他人接诊 → 403（归属校验与 auto_save_draft 同口径）
"""
from datetime import date, datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User
from app.services.medical_record_service import MedicalRecordService


def _user(uid: str, role: str = "doctor"):
    return User(id=uid, username=f"u_{uid}", password_hash="x", real_name="测试", role=role, is_active=True)


@pytest_asyncio.fixture
async def seeded(async_db):
    """doc-me 的住院接诊，存两份不同类型草稿。"""
    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-me",
        visit_type="inpatient", status="in_progress", visited_at=datetime(2026, 8, 1),
    ))
    async_db.add(Encounter(
        id="enc-other", patient_id="p1", doctor_id="doc-other",
        visit_type="inpatient", status="in_progress", visited_at=datetime(2026, 8, 1),
    ))
    await async_db.commit()
    svc = MedicalRecordService(async_db)
    await svc.save_ai_draft("enc-1", "admission_note", "入院记录草稿全文", "doc-me")
    await svc.save_ai_draft("enc-1", "first_course_record", "首程草稿全文", "doc-me")


@pytest_asyncio.fixture
async def client(async_db, seeded) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: _user("doc-me")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_draft_by_type_returns_matching_row(client):
    r = await client.get(
        "/api/v1/medical-records/draft-by-type",
        params={"encounter_id": "enc-1", "record_type": "admission_note"},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["exists"] is True
    assert d["content"] == "入院记录草稿全文"
    assert d["status"] == "editing"
    assert d["updated_at"], "必须返回 updated_at 供前端同步 auto-save 基线"


@pytest.mark.asyncio
async def test_draft_by_type_isolates_types(client):
    """不同文书类型各回各的行——不会拿 active（最新）行冒充。"""
    r = await client.get(
        "/api/v1/medical-records/draft-by-type",
        params={"encounter_id": "enc-1", "record_type": "first_course_record"},
    )
    assert r.json()["content"] == "首程草稿全文"


@pytest.mark.asyncio
async def test_draft_by_type_missing_returns_exists_false(client):
    r = await client.get(
        "/api/v1/medical-records/draft-by-type",
        params={"encounter_id": "enc-1", "record_type": "discharge_record"},
    )
    assert r.status_code == 200
    assert r.json() == {"exists": False}


@pytest.mark.asyncio
async def test_draft_by_type_denies_foreign_encounter(client):
    r = await client.get(
        "/api/v1/medical-records/draft-by-type",
        params={"encounter_id": "enc-other", "record_type": "admission_note"},
    )
    assert r.status_code == 403
