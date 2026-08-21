# -*- coding: utf-8 -*-
"""诊断条目结构化测试（2026-08-21 阶段1a）。

覆盖：
  - 整组替换写入 + 读取排序（主诊断优先）
  - 业务校验：中医病/证至多一条、主诊断至多一条、未标主时自动补
    （规则与 HIS 回写 builder 既有隐式逻辑一致：西医优先为主）
  - 文本投影双写：写条目后 inquiry_inputs 旧三列被同步（LLM/渲染/QC 文本
    链路的输入源），多条西医编号串接、主诊断排首位
  - 端点归属守卫：他人接诊 403
"""
from datetime import date, datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter, InquiryInput
from app.models.patient import Patient
from app.models.user import User


def _user(uid: str, role: str = "doctor"):
    return User(id=uid, username=f"u_{uid}", password_hash="x", real_name="王医生", role=role, is_active=True)


@pytest_asyncio.fixture
async def seeded(async_db):
    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-me",
        visit_type="inpatient", status="in_progress", visited_at=datetime(2026, 8, 21),
    ))
    async_db.add(Encounter(
        id="enc-other", patient_id="p1", doctor_id="doc-other",
        visit_type="inpatient", status="in_progress", visited_at=datetime(2026, 8, 21),
    ))
    # 既有问诊行（验证投影写回最新版）
    async_db.add(InquiryInput(encounter_id="enc-1", version=1))
    await async_db.commit()


@pytest_asyncio.fixture
async def client(async_db, seeded) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: _user("doc-me")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_replace_and_list_with_projection(client, async_db):
    """写入两条西医+中医病证 → 读取主诊断在首、投影三列同步。"""
    payload = {"items": [
        {"category": "western", "name": "2型糖尿病", "is_primary": False, "sort_order": 1},
        {"category": "western", "name": "高血压病", "is_primary": True, "sort_order": 0,
         "admission_condition": "有"},
        {"category": "tcm_disease", "name": "眩晕病"},
        {"category": "tcm_syndrome", "name": "肝阳上亢证"},
    ]}
    r = await client.put("/api/v1/encounters/enc-1/diagnoses", json=payload)
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 4

    r = await client.get("/api/v1/encounters/enc-1/diagnoses")
    listed = r.json()
    assert listed[0]["name"] == "高血压病" and listed[0]["is_primary"] is True
    assert listed[0]["admission_condition"] == "有"

    # 投影双写：旧三列被同步（主诊断排首、多条编号）
    inq = (await async_db.execute(
        select(InquiryInput).where(InquiryInput.encounter_id == "enc-1")
        .order_by(InquiryInput.version.desc()).limit(1)
    )).scalar_one()
    assert inq.western_diagnosis == "1.高血压病；2.2型糖尿病"
    assert inq.tcm_disease_diagnosis == "眩晕病"
    assert inq.tcm_syndrome_diagnosis == "肝阳上亢证"


@pytest.mark.asyncio
async def test_auto_primary_fallback_prefers_western(client):
    """一条主诊断都没标时自动补：西医优先（与 HIS 回写既有规则一致）。"""
    payload = {"items": [
        {"category": "tcm_disease", "name": "感冒"},
        {"category": "western", "name": "急性上呼吸道感染"},
    ]}
    r = await client.put("/api/v1/encounters/enc-1/diagnoses", json=payload)
    assert r.status_code == 200
    primary = [i for i in r.json() if i["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["name"] == "急性上呼吸道感染"


@pytest.mark.asyncio
async def test_validation_rejects_dual_primary_and_dual_tcm(client):
    """主诊断>1 条、中医病>1 条均 422。"""
    r = await client.put("/api/v1/encounters/enc-1/diagnoses", json={"items": [
        {"category": "western", "name": "甲", "is_primary": True},
        {"category": "western", "name": "乙", "is_primary": True},
    ]})
    assert r.status_code == 422
    r = await client.put("/api/v1/encounters/enc-1/diagnoses", json={"items": [
        {"category": "tcm_disease", "name": "甲"},
        {"category": "tcm_disease", "name": "乙"},
    ]})
    assert r.status_code == 422
    # 非法入院病情枚举
    r = await client.put("/api/v1/encounters/enc-1/diagnoses", json={"items": [
        {"category": "western", "name": "甲", "admission_condition": "可能有"},
    ]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_foreign_encounter_denied(client):
    """他人接诊读写均 403（归属守卫与问诊同口径）。"""
    r = await client.get("/api/v1/encounters/enc-other/diagnoses")
    assert r.status_code == 403
    r = await client.put("/api/v1/encounters/enc-other/diagnoses", json={"items": []})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_empty_replace_clears_and_projects_empty(client, async_db):
    """清空列表：条目删光、投影三列清空。"""
    await client.put("/api/v1/encounters/enc-1/diagnoses", json={"items": [
        {"category": "western", "name": "高血压病"},
    ]})
    r = await client.put("/api/v1/encounters/enc-1/diagnoses", json={"items": []})
    assert r.status_code == 200 and r.json() == []
    inq = (await async_db.execute(
        select(InquiryInput).where(InquiryInput.encounter_id == "enc-1")
        .order_by(InquiryInput.version.desc()).limit(1)
    )).scalar_one()
    assert inq.western_diagnosis == ""
