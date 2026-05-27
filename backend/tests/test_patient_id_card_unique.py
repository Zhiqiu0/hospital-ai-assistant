"""patients.id_card 唯一性测试

锁死 2026-05-27 加的 partial unique index + service 层去重：
  - 同身份证只能存在一份活跃档案
  - 软删的旧档案不占用身份证（可以重新建档）
  - 改身份证时不能撞别人

注意：测试用 SQLite（conftest 把 JSONB 替换成 JSON），SQLite 不支持 PostgreSQL
的 partial unique index 语法，所以 DB 层的"严"靠生产 PG；本测试只覆盖
service 层的"宽 App 检查"。
"""
import pytest
from fastapi import HTTPException

from app.schemas.patient import PatientCreate, PatientUpdate
from app.services.patient_service import PatientService


_VALID_ID_CARD = "110101199001011237"  # 真合法 18 位 + GB 校验码


@pytest.mark.asyncio
async def test_create_with_duplicate_id_card_raises_409(async_db):
    """同身份证已有活跃档案 → 第二次 create 应抛 409 + 含已有 patient_id"""
    svc = PatientService(async_db)
    p1 = await svc.create(PatientCreate(
        name="原档案", gender="male", birth_date="1990-01-01",
        id_card=_VALID_ID_CARD,
    ))
    assert p1["id"]

    with pytest.raises(HTTPException) as exc:
        await svc.create(PatientCreate(
            name="第二个", gender="male", birth_date="1990-01-01",
            id_card=_VALID_ID_CARD,
        ))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "patient_id_card_conflict"
    assert exc.value.detail["existing_patient_id"] == p1["id"]


@pytest.mark.asyncio
async def test_create_after_soft_delete_succeeds(async_db):
    """原档案软删后，同身份证可以重新建档（业务上等于"误删恢复"的备用路径）"""
    from app.models.patient import Patient
    svc = PatientService(async_db)
    p1 = await svc.create(PatientCreate(
        name="软删前", gender="male", birth_date="1990-01-01",
        id_card=_VALID_ID_CARD,
    ))
    # 模拟取消接诊后的软删
    patient = await async_db.get(Patient, p1["id"])
    patient.is_deleted = True
    await async_db.commit()

    # 现在应该可以重新建档
    p2 = await svc.create(PatientCreate(
        name="重新建档", gender="male", birth_date="1990-01-01",
        id_card=_VALID_ID_CARD,
    ))
    assert p2["id"] != p1["id"]
    assert p2["name"] == "重新建档"


@pytest.mark.asyncio
async def test_create_without_id_card_allowed(async_db):
    """无身份证（婴儿/无证患者）允许多人 → id_card NULL 不参与唯一约束"""
    svc = PatientService(async_db)
    p1 = await svc.create(PatientCreate(name="无证甲", gender="male", birth_date="2026-01-01"))
    p2 = await svc.create(PatientCreate(name="无证乙", gender="female", birth_date="2026-01-02"))
    assert p1["id"] != p2["id"]


@pytest.mark.asyncio
async def test_update_id_card_to_another_patient_raises_409(async_db):
    """改 id_card 撞别人 → 409，不允许把自己的身份证号改成已被别人占用的"""
    svc = PatientService(async_db)
    other = await svc.create(PatientCreate(
        name="他人", gender="male", birth_date="1990-01-01",
        id_card=_VALID_ID_CARD,
    ))
    me = await svc.create(PatientCreate(
        name="我", gender="male", birth_date="1985-06-15",
        # 另一个真实合法身份证号（GB 11643-1999 校验码）
        id_card="130101198506150012",
    ))

    with pytest.raises(HTTPException) as exc:
        await svc.update(me["id"], PatientUpdate(
            id_card=_VALID_ID_CARD,
            birth_date="1990-01-01",  # 也要改 birth_date 保持一致性，否则被另一个校验拦下
        ))
    assert exc.value.status_code == 409
    assert exc.value.detail["existing_patient_id"] == other["id"]


@pytest.mark.asyncio
async def test_update_keep_same_id_card_no_conflict(async_db):
    """改其他字段不动 id_card → 不应触发查重"""
    svc = PatientService(async_db)
    p = await svc.create(PatientCreate(
        name="原名", gender="male", birth_date="1990-01-01",
        id_card=_VALID_ID_CARD,
    ))
    # 不传 id_card，只改姓名 → 不应该自查重把自己拦下来
    updated = await svc.update(p["id"], PatientUpdate(name="新名"))
    assert updated["name"] == "新名"
    assert updated["id_card"] == _VALID_ID_CARD
