"""
患者匹配逻辑单元测试
规则：
  1. 身份证号单独可匹配
  2. 手机号必须同时匹配姓名
  3. 姓名 + 生日可匹配
  4. 手机号单独不能匹配
"""
import pytest
import pytest_asyncio
from datetime import date
from app.models.patient import Patient
from app.services.patient_service import PatientService


@pytest_asyncio.fixture
async def patient(async_db):
    p = Patient(
        name="张三",
        phone="13800138000",
        id_card="330102199001011234",
        birth_date=date(1990, 1, 1),
    )
    async_db.add(p)
    await async_db.commit()
    return p


@pytest.mark.asyncio
async def test_find_by_id_card(async_db, patient):
    svc = PatientService(async_db)
    result = await svc.find_existing(id_card="330102199001011234")
    assert result is not None
    assert result["name"] == "张三"


@pytest.mark.asyncio
async def test_find_by_phone_and_name(async_db, patient):
    svc = PatientService(async_db)
    result = await svc.find_existing(phone="13800138000", name="张三")
    assert result is not None


@pytest.mark.asyncio
async def test_find_by_name_and_birth_date(async_db, patient):
    svc = PatientService(async_db)
    result = await svc.find_existing(name="张三", birth_date=date(1990, 1, 1))
    assert result is not None


@pytest.mark.asyncio
async def test_phone_alone_cannot_match(async_db, patient):
    """手机号单独不能匹配患者（防止误合并）"""
    svc = PatientService(async_db)
    result = await svc.find_existing(phone="13800138000")
    assert result is None


@pytest.mark.asyncio
async def test_phone_with_wrong_name_cannot_match(async_db, patient):
    """手机号 + 错误姓名不能匹配"""
    svc = PatientService(async_db)
    result = await svc.find_existing(phone="13800138000", name="李四")
    assert result is None


@pytest.mark.asyncio
async def test_unknown_patient_returns_none(async_db):
    svc = PatientService(async_db)
    result = await svc.find_existing(id_card="000000000000000000")
    assert result is None
