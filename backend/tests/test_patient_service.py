"""
患者匹配逻辑单元测试
规则：
  1. 身份证号单独可匹配
  2. 手机号必须同时匹配姓名
  3. 姓名 + 生日可匹配
  4. 手机号单独不能匹配
新增：
  5. search 支持中文姓名子串
  6. search 支持拼音全拼
  7. search 支持首字母
  8. search 支持混拼
"""
import pytest
import pytest_asyncio
from datetime import date
from app.models.patient import Patient
from app.schemas.patient import PatientCreate
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


# ── 拼音搜索：通过 service.create 走完整路径，验证 name_pinyin 正确回填 + 检索命中 ──

@pytest_asyncio.fixture
async def zhang_san(async_db):
    """通过 PatientService.create 创建张三（自动回填拼音索引）。"""
    svc = PatientService(async_db)
    await svc.create(PatientCreate(name="张三", phone="13900139000"))
    return svc


@pytest.mark.asyncio
async def test_search_by_chinese_name(zhang_san):
    """中文子串仍然命中（保留原有行为）。"""
    result = await zhang_san.search("张", page=1, page_size=10)
    assert result["total"] == 1
    assert result["items"][0]["name"] == "张三"


@pytest.mark.asyncio
async def test_search_by_full_pinyin(zhang_san):
    """全拼"zhangsan"应命中张三。"""
    result = await zhang_san.search("zhangsan", page=1, page_size=10)
    assert result["total"] == 1
    assert result["items"][0]["name"] == "张三"


@pytest.mark.asyncio
async def test_search_by_pinyin_prefix(zhang_san):
    """拼音前缀"zhang"也应命中——子串 ILIKE 自动覆盖。"""
    result = await zhang_san.search("zhang", page=1, page_size=10)
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_search_by_initials(zhang_san):
    """首字母"zs"命中张三（市面搜索框标准能力）。"""
    result = await zhang_san.search("zs", page=1, page_size=10)
    assert result["total"] == 1
    assert result["items"][0]["name"] == "张三"


@pytest.mark.asyncio
async def test_search_by_mixed_pinyin(zhang_san):
    """混拼"zsan"=z(张)+san(三) 也要命中——市面搜索框关键差异点。"""
    result = await zhang_san.search("zsan", page=1, page_size=10)
    assert result["total"] == 1
    assert result["items"][0]["name"] == "张三"


@pytest.mark.asyncio
async def test_search_pinyin_case_insensitive(zhang_san):
    """大小写不敏感（医生爱按大写锁打首字母）。"""
    result = await zhang_san.search("ZS", page=1, page_size=10)
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_search_pinyin_no_match(zhang_san):
    """不相关拼音不应误命中。"""
    result = await zhang_san.search("liwang", page=1, page_size=10)
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_update_name_refreshes_pinyin(async_db):
    """改名后老拼音应失效，新拼音应命中。"""
    from app.schemas.patient import PatientUpdate
    svc = PatientService(async_db)
    created = await svc.create(PatientCreate(name="张三"))
    # 改名为"李四"
    await svc.update(created["id"], PatientUpdate(name="李四"))
    # 老拼音搜不到
    old = await svc.search("zhangsan", page=1, page_size=10)
    assert old["total"] == 0
    # 新拼音命中
    new = await svc.search("lisi", page=1, page_size=10)
    assert new["total"] == 1
    assert new["items"][0]["name"] == "李四"
