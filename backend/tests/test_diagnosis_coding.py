# -*- coding: utf-8 -*-
"""诊断编码化测试（2026-08-21 阶段2）。

覆盖：
  - 字典检索端点三路匹配（名称/拼音首字母/编码前缀）与排序（前缀优先、短名优先）
  - 保存时确定性自动补码（名称精确匹配；同名多码不补；类别隔离）
  - HIS 回写切结构化源：条目带 code/code_type（TCD→GB95 映射）、
    主诊断取医生显式标注；无条目时回落旧文本行为
"""
from datetime import date, datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import DiagnosisCode, Encounter, InquiryInput
from app.models.patient import Patient
from app.models.user import User
from app.his_adapter.writeback_builder import build_writeback_payload
from app.schemas.diagnosis import DiagnosisItemIn
from app.services.diagnosis_service import DiagnosisService


def _user(uid: str, role: str = "doctor"):
    return User(id=uid, username=f"u_{uid}", password_hash="x", real_name="王医生", role=role, is_active=True)


_DICT = [
    ("I10.x00", "特发性高血压", "ICD10", "tfxgxy"),
    ("I10.x09", "原发性高血压", "ICD10", "yfxgxy"),
    ("E11.900", "2型糖尿病", "ICD10", "2xtnb"),
    ("A01.01.01", "感冒", "TCD_DIS", "gm"),
    ("B04.02.01.04.02.01", "肝阳上亢证", "TCD_SYN", "gysgz"),
    # 同名多码场景（构造）：两条同名 ICD10 → 自动补码必须放弃
    ("Z99.001", "同名测试诊断", "ICD10", "tmcszd"),
    ("Z99.002", "同名测试诊断", "ICD10", "tmcszd"),
]


@pytest_asyncio.fixture
async def seeded(async_db):
    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-me", visit_type="outpatient",
        status="in_progress", visited_at=datetime(2026, 8, 21),
        his_external_ref={"his_visit_no": "V001", "doctor_code": "D01"},
    ))
    async_db.add(InquiryInput(encounter_id="enc-1", version=1))
    for code, name, ctype, py in _DICT:
        async_db.add(DiagnosisCode(code=code, name=name, code_type=ctype, pinyin_initial=py))
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
async def test_search_by_name_pinyin_and_code(client):
    # 名称包含
    r = await client.get("/api/v1/diagnosis-codes/search?q=高血压&code_type=ICD10")
    names = [i["name"] for i in r.json()]
    assert "原发性高血压" in names and "特发性高血压" in names
    # 拼音首字母前缀
    r = await client.get("/api/v1/diagnosis-codes/search?q=yfxgxy&code_type=ICD10")
    assert r.json()[0]["name"] == "原发性高血压"
    # 编码前缀
    r = await client.get("/api/v1/diagnosis-codes/search?q=I10&code_type=ICD10")
    assert {i["code"] for i in r.json()} >= {"I10.x00", "I10.x09"}
    # 类型隔离：中医字典查不到西医词
    r = await client.get("/api/v1/diagnosis-codes/search?q=高血压&code_type=TCD_DIS")
    assert r.json() == []


@pytest.mark.asyncio
async def test_auto_fill_codes_on_save(client, async_db):
    """保存无码条目：名称精确匹配自动补码；同名多码/查无此名不补。"""
    r = await client.put("/api/v1/encounters/enc-1/diagnoses", json={"items": [
        {"category": "western", "name": "原发性高血压", "is_primary": True},
        {"category": "western", "name": "同名测试诊断", "sort_order": 1},
        {"category": "western", "name": "字典没有的罕见病", "sort_order": 2},
        {"category": "tcm_syndrome", "name": "肝阳上亢证"},
    ]})
    assert r.status_code == 200, r.text
    by_name = {i["name"]: i for i in r.json()}
    assert by_name["原发性高血压"]["code"] == "I10.x09"
    assert by_name["原发性高血压"]["code_type"] == "ICD10"
    assert by_name["同名测试诊断"]["code"] is None, "同名多码必须放弃自动补（宁缺勿错）"
    assert by_name["字典没有的罕见病"]["code"] is None
    assert by_name["肝阳上亢证"]["code"] == "B04.02.01.04.02.01"
    assert by_name["肝阳上亢证"]["code_type"] == "TCD_SYN"


@pytest.mark.asyncio
async def test_writeback_uses_structured_entries_with_codes(client, async_db):
    """回写 diagnoses[] 来自条目表：带 code/code_type（TCD→GB95），主诊断显式。"""
    await client.put("/api/v1/encounters/enc-1/diagnoses", json={"items": [
        {"category": "western", "name": "2型糖尿病", "is_primary": False, "sort_order": 1},
        {"category": "western", "name": "原发性高血压", "is_primary": True, "sort_order": 0},
        {"category": "tcm_syndrome", "name": "肝阳上亢证"},
    ]})
    payload = await build_writeback_payload(async_db, "enc-1")
    dx = payload["diagnoses"]
    assert dx[0]["name"] == "原发性高血压" and dx[0]["is_primary"] is True
    assert dx[0]["code"] == "I10.x09" and dx[0]["code_type"] == "ICD10"
    syn = next(d for d in dx if d["category"] == "tcm_syndrome")
    assert syn["code_type"] == "GB95", "中医编码回写必须映射为规范枚举 GB95"


@pytest.mark.asyncio
async def test_writeback_falls_back_to_text_fields(async_db, seeded):
    """无条目时回落旧文本三字段拼装（行为与切换前一致）。"""
    from sqlalchemy import update
    await async_db.execute(
        update(InquiryInput).where(InquiryInput.encounter_id == "enc-1")
        .values(western_diagnosis="急性上呼吸道感染", tcm_disease_diagnosis="感冒")
    )
    await async_db.commit()
    payload = await build_writeback_payload(async_db, "enc-1")
    dx = payload["diagnoses"]
    assert dx[0] == {"name": "急性上呼吸道感染", "is_primary": True, "category": "western"}
    assert dx[1]["category"] == "tcm_disease" and dx[1]["is_primary"] is False


@pytest.mark.asyncio
async def test_search_code_prefix_ignores_dots(client):
    """编码检索忽略点号（2026-08-22 用户实测）：a010102 与 a01.01.02 同样命中。"""
    r = await client.get("/api/v1/diagnosis-codes/search?q=b0402010402&code_type=TCD_SYN")
    assert any(i["code"] == "B04.02.01.04.02.01" for i in r.json()), "去点编码应命中"
    # 大小写不敏感（2026-08-22 终验实锤）：ICD 医保码含小写 x（I10.x09），
    # 输入 i10x09/I10X09 都必须命中——旧实现只 upper 输入导致含 x 码段永不命中
    r = await client.get("/api/v1/diagnosis-codes/search?q=i10x09&code_type=ICD10")
    assert any(i["code"] == "I10.x09" for i in r.json()), "小写x码段去点应命中"
    r = await client.get("/api/v1/diagnosis-codes/search?q=I10.X09&code_type=ICD10")
    assert any(i["code"] == "I10.x09" for i in r.json()), "大写X带点也应命中"
    # 带点写法照常可用
    r = await client.get("/api/v1/diagnosis-codes/search?q=B04.02&code_type=TCD_SYN")
    assert any(i["code"].startswith("B04.02") for i in r.json())
