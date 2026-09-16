# -*- coding: utf-8 -*-
"""患者历史病历端点的角色收口回归锁（2026-09-16 覆盖率盲区 #5）。

背景：GET /medical-records/by-patient/{id} 的角色收口是 2026-08-29 第六轮
渗透审计的修复（qc_officer 经此绕过 /qc/* 的科室隔离读全院患者全文），
但修复后**没有回归锁**——403 门与 view_records 审计留痕（等保 2.0 三级
要求）这段从未被测试执行过，回归即静默重开渗透报告里的洞。
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.patient import Patient
from app.models.user import User


def _user(role, uid=None):
    uid = uid or f"u-{role}"
    return User(id=uid, username=f"u_{role}", password_hash="x",
                real_name=f"测试{role}", role=role, is_active=True)


async def _call(async_db, user, patient_id):
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            return await ac.get(f"/api/v1/medical-records/by-patient/{patient_id}")
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def patient_id(async_db):
    p = Patient(name="收口测试", gender="female")
    async_db.add(p)
    await async_db.commit()
    return p.id


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["qc_officer", "nurse", "radiologist"])
async def test_非医生角色读患者历史被403(async_db, patient_id, role):
    """渗透报告原话：质控员经此端点绕过科室隔离读全院患者全文。"""
    r = await _call(async_db, _user(role), patient_id)
    assert r.status_code == 403, f"{role} 未被拦（{r.status_code}）——渗透洞重开"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["doctor", "super_admin", "hospital_admin"])
async def test_医生与管理角色放行(async_db, patient_id, role):
    r = await _call(async_db, _user(role), patient_id)
    assert r.status_code == 200, f"{role} 被误拦（{r.status_code}）——全院共享读被打断"


@pytest.mark.asyncio
async def test_查阅必留审计痕迹(async_db, patient_id, monkeypatch):
    """等保 2.0 三级：谁何时查了哪个患者必须可追溯。log_action 走独立会话，
    патч 到测试会话上才可断言（与 qc_report 落库测试同一手法）。"""
    from app.services import audit_service

    class _Same:
        async def __aenter__(self):
            return async_db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(audit_service, "AsyncSessionLocal", lambda: _Same())

    r = await _call(async_db, _user("doctor"), patient_id)
    assert r.status_code == 200
    row = (await async_db.execute(
        select(AuditLog).where(
            AuditLog.action == "view_records",
            AuditLog.resource_id == patient_id,
        )
    )).scalars().first()
    assert row is not None, "查阅未留 view_records 审计——等保留痕缺失"
    assert row.user_id == "u-doctor"
