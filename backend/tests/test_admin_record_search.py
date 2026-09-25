"""管理端搜索在数据库分页前执行，保留签发状态、医生过滤和管理员权限。"""
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.api.v1.admin.records import router
from app.core.security import get_current_user
from app.database import get_db
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.user import User


@pytest_asyncio.fixture
async def search_client(async_db):
    """轻量ASGI路由使用真实查询与权限依赖，仅替换认证身份和内存数据库。"""
    doctors = [User(id=f"d{i}", username=f"doctor{i}", real_name=name,
                    role="doctor", password_hash="fake")
               for i, name in enumerate(["张医生", "李医生"])]
    async_db.add_all(doctors)
    await async_db.flush()
    for i in range(24):
        # 目标在默认第一页之外；末条是草稿，搜索不能把它放出来。
        name = "跨页患者" if i in (21, 22, 23) else f"普通患者{i}"
        patient = Patient(id=f"p{i}", name=name, gender="男")
        encounter = Encounter(id=f"e{i}", patient_id=patient.id,
                              doctor_id=f"d{i % 2}", visit_type="outpatient")
        record = MedicalRecord(id=f"r{i}", encounter_id=encounter.id,
                               record_type="outpatient", status="draft" if i == 23 else "submitted",
                               submitted_at=datetime(2026, 9, 1) - timedelta(minutes=i))
        async_db.add_all([patient, encounter, record])
        await async_db.flush()
    app = FastAPI()
    app.include_router(router, prefix="/admin/records")
    identity = User(id="admin", username="admin", real_name="管理员", role="hospital_admin", password_hash="fake")

    async def database():
        """提供每个用例独立的SQLite会话。"""
        yield async_db

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: identity
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, identity


@pytest.mark.asyncio
async def test_search_finds_chinese_patient_beyond_first_page(search_client):
    """搜索先过滤再计数分页，并去除首尾空白。"""
    client, _ = search_client
    first = (await client.get("/admin/records")).json()
    assert "r21" not in [r["id"] for r in first["items"]]
    result = (await client.get("/admin/records", params={"search": "  跨页  ", "page_size": 1, "page": 2})).json()
    assert result["total"] == 2
    assert [r["id"] for r in result["items"]] == ["r22"]


@pytest.mark.asyncio
@pytest.mark.parametrize("search,doctor_id,total", [("李医生", None, 11), ("跨页", "d0", 1), ("  ", None, 23), ("%", None, 0), ("' OR 1=1 --", None, 0)])
async def test_search_keeps_doctor_and_submitted_filters(search_client, search, doctor_id, total):
    """姓名包含匹配使用绑定参数，通配符按字面量解释，空白等同不搜索。"""
    client, _ = search_client
    params = {"search": search}
    if doctor_id:
        params["doctor_id"] = doctor_id
    response = await client.get("/admin/records", params=params)
    assert response.status_code == 200
    assert response.json()["total"] == total


@pytest.mark.asyncio
async def test_search_length_and_admin_permission(search_client):
    """输入最多100字符，普通医生仍无管理端读取权限。"""
    client, identity = search_client
    assert (await client.get("/admin/records", params={"search": "张" * 101})).status_code == 422
    identity.role = "doctor"
    assert (await client.get("/admin/records", params={"search": "张"})).status_code == 403
