"""路由级归属校验回归（IDOR 修复）

背景：core/authz.py 里的 assert_patient_access / assert_encounter_access 早就写好并
在 PACS 用对了，但 patients.py / encounters.py / medical_records.py 的一批端点当时
「漏挂」——单元测试只测了 helper 本身，没测「路由是否真的调用了 helper」，导致越权
（医生能读任意患者身份证号/PHI）在真实请求里长期存在。本文件用 HTTP 级请求覆盖这条
「路由确实挂了校验」的契约，防止再退化。

覆盖：
  - 非接诊医生访问他人患者详情/档案 → 403；对自己接诊过的患者 → 200
  - 非接诊医生访问他人接诊详情 / previous-record → 403
  - 病历 quick_save / auto_save_draft 越权 → 403
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


def _override_user(uid: str, role: str = "doctor"):
    """返回一个能被 get_current_user 覆盖使用的假用户（authz 只读 id/role）。"""
    return User(id=uid, username=f"u_{uid}", password_hash="x", real_name="测试", role=role, is_active=True)


@pytest_asyncio.fixture
async def seeded(async_db):
    """建两个患者：一个 doc-me 接诊过（own），一个只有 doc-other 接诊过（other）。"""
    own = Patient(id="pat-own", name="我的患者", birth_date=date(1970, 1, 1))
    other = Patient(id="pat-other", name="他人患者", birth_date=date(1980, 1, 1))
    async_db.add_all([own, other])
    await async_db.commit()

    enc_own = Encounter(
        id="enc-own", patient_id=own.id, doctor_id="doc-me",
        visit_type="outpatient", status="in_progress", visited_at=datetime(2026, 4, 1),
    )
    enc_other = Encounter(
        id="enc-other", patient_id=other.id, doctor_id="doc-other",
        visit_type="outpatient", status="in_progress", visited_at=datetime(2026, 4, 1),
    )
    async_db.add_all([enc_own, enc_other])
    await async_db.commit()
    return {"own": own, "other": other, "enc_own": enc_own, "enc_other": enc_other}


@pytest_asyncio.fixture
async def client_doc_me(async_db, seeded) -> AsyncGenerator[AsyncClient, None]:
    """以 doc-me 身份发请求（他接诊过 pat-own，没接诊过 pat-other）。"""
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: _override_user("doc-me")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patient_detail_cross_doctor_blocked(client_doc_me):
    """医生读没接诊过的患者详情 → 403（IDOR 修复核心）。"""
    r = await client_doc_me.get("/api/v1/patients/pat-other")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patient_profile_cross_doctor_blocked(client_doc_me):
    """医生读没接诊过的患者档案（过敏/既往等 PHI）→ 403。"""
    r = await client_doc_me.get("/api/v1/patients/pat-other/profile")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patient_own_allowed(client_doc_me):
    """医生读自己接诊过的患者 → 200（不能误伤正常业务）。"""
    r = await client_doc_me.get("/api/v1/patients/pat-own")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_encounter_detail_cross_doctor_blocked(client_doc_me):
    """医生读他人接诊详情 → 403。"""
    r = await client_doc_me.get("/api/v1/encounters/enc-other")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_previous_record_cross_doctor_blocked(client_doc_me):
    """医生对他人接诊拉 previous-record → 403（否则可套出他人患者历史问诊）。"""
    r = await client_doc_me.get("/api/v1/encounters/enc-other/previous-record")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_quick_save_cross_doctor_blocked(client_doc_me):
    """医生在他人接诊上签发病历 → 403（篡改他人医疗文书）。"""
    r = await client_doc_me.post(
        "/api/v1/medical-records/quick-save",
        json={"encounter_id": "enc-other", "record_type": "outpatient", "content": "x"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_auto_save_draft_cross_doctor_blocked(client_doc_me):
    """医生给他人接诊自动保存草稿 → 403。"""
    r = await client_doc_me.post(
        "/api/v1/medical-records/auto-save-draft",
        json={"encounter_id": "enc-other", "record_type": "outpatient", "content": "x"},
    )
    assert r.status_code == 403


# ── 2026-08-13 第二轮审计补的三条守卫 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_create_record_cross_doctor_blocked(client_doc_me):
    """医生在他人接诊下创建病历 → 403。

    原先本端点零校验：任何登录医生都能在别人接诊下凭空建出 record，
    后续版本写入以 record_id 为起点，归属判定的源头就被污染了。
    """
    r = await client_doc_me.post(
        "/api/v1/medical-records",
        json={"encounter_id": "enc-other", "record_type": "outpatient"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_record_own_encounter_allowed(client_doc_me):
    """自己的接诊下建病历 → 201（不能误伤正常业务）。"""
    r = await client_doc_me.post(
        "/api/v1/medical-records",
        json={"encounter_id": "enc-own", "record_type": "outpatient"},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_patient_list_excludes_sensitive_phi(client_doc_me):
    """患者列表不得返回身份证/住址/紧急联系人等病案首页级 PHI。

    原先列表复用完整响应，任何登录医生翻页即可批量导出全院身份信息库；
    这些字段现在只在带归属校验 + 审计的详情端点返回。
    """
    r = await client_doc_me.get("/api/v1/patients?page=1&page_size=50")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "列表应返回患者（否则本用例失去判别力）"
    forbidden = {"id_card", "address", "ethnicity", "marital_status", "occupation",
                 "workplace", "contact_name", "contact_phone", "contact_relation",
                 "blood_type"}
    for item in items:
        leaked = forbidden & set(item)
        assert not leaked, f"患者列表泄露敏感字段：{leaked}"
    # 检索必需字段仍在（不能把功能砍废）
    assert {"id", "name"} <= set(items[0])


@pytest_asyncio.fixture
async def patched_audit_session(async_db, monkeypatch):
    """audit_service 用模块级 AsyncSessionLocal 直连真实库——patch 成复用测试
    session，让审计写入能被断言读到（与 test_admin_audit_dep 同款做法）。"""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_session_factory():
        yield async_db

    monkeypatch.setattr(
        "app.services.audit_service.AsyncSessionLocal", _fake_session_factory
    )
    yield


@pytest.mark.asyncio
async def test_profile_update_writes_audit(client_doc_me, async_db, patched_audit_session):
    """修改患者档案（过敏史等纵向 PHI）必须留审计——原先零留痕。"""
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    r = await client_doc_me.put(
        "/api/v1/patients/pat-own/profile",
        json={"allergy_history": "青霉素过敏"},
    )
    assert r.status_code == 200
    rows = (await async_db.execute(
        select(AuditLog).where(AuditLog.action == "update_patient_profile")
    )).scalars().all()
    assert rows, "档案修改未写审计日志"
    assert rows[0].resource_id == "pat-own"
    # 只记字段名不记内容（PHI 不进审计明细）
    assert "青霉素" not in (rows[0].detail or "")
