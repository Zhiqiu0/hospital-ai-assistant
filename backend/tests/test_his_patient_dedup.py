"""HIS 患者查重 / 脏数据降级回归测试（2026-08-14 第七轮审计）。

两条都直接关系到「病历挂错人 / 病历散在多份档案」，是本项目的第一优先级。

  #16 查重不归一：HIS 推来小写 x 的身份证 → 查重 miss → 新建 →
      PatientCreate 归一成大写 X → 撞 uq_patients_id_card_active 唯一索引 →
      ack 50000 → **该患者此后每次复诊都推不进来**。
  #17 脏数据降级过度：任一字段校验不过就把 id_card 和 phone 一起丢掉 →
      档案落库时一个强键都没有 → 每次复诊都新建一份档案。
"""

import pytest
from pydantic import ValidationError

from app.schemas.patient import PatientCreate
from app.services.patient_service import PatientService

# 一个校验码正确的测试身份证（GB 11643-1999）
_ID = "11010519491231002X"


async def _make_patient(db, **over):
    """建一份基础档案，返回其 id。"""
    fields = {"name": "张三", "gender": "男", "id_card": _ID, "phone": "13800138000"}
    fields.update(over)
    created = await PatientService(db).create(PatientCreate(**fields), commit=False)
    await db.flush()
    return created["id"]


# ── #16 查重归一化 ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_身份证末位小写x也能查重命中(async_db):
    pid = await _make_patient(async_db)
    found = await PatientService(async_db).find_existing(
        id_card=_ID[:-1] + "x", allow_weak_match=False
    )
    assert found is not None, "小写 x 查重 miss —— 复诊会撞唯一索引 ack 50000"
    assert found["id"] == pid


@pytest.mark.asyncio
async def test_身份证带空格也能查重命中(async_db):
    pid = await _make_patient(async_db)
    found = await PatientService(async_db).find_existing(
        id_card="1101 0519 4912 3100 2x", allow_weak_match=False
    )
    assert found is not None
    assert found["id"] == pid


@pytest.mark.asyncio
async def test_手机号带国家码和连字符也能查重命中(async_db):
    pid = await _make_patient(async_db, id_card=None)
    found = await PatientService(async_db).find_existing(
        phone="+86-138-0013-8000", name="张三", allow_weak_match=False
    )
    assert found is not None
    assert found["id"] == pid


@pytest.mark.asyncio
async def test_归一化后仍不是同一人则不应命中(async_db):
    """防过度归一：别把不同的号码归一到一起。"""
    await _make_patient(async_db)
    found = await PatientService(async_db).find_existing(
        id_card="110105194912310038", allow_weak_match=False
    )
    assert found is None


# ── #17 脏数据逐字段降级 ─────────────────────────────────────────────────────

def test_手机号脏数据不应连累身份证():
    """HIS 最常见的脏数据是手机号（座机/空号），身份证往往是好的。

    复刻 _find_or_create_patient 的降级逻辑：逐字段试探，只丢不合格的那个。
    """
    fields = {"name": "李四", "gender": "男", "birth_date": None,
              "id_card": _ID, "phone": "0571-88886666"}  # 座机

    with pytest.raises(ValidationError):
        PatientCreate(**fields)  # 前提：整体确实校验不过

    for field in ("id_card", "phone"):
        if fields[field] is None:
            continue
        probe = {**fields, "id_card": None, "phone": None, field: fields[field]}
        try:
            PatientCreate(**probe)
        except ValidationError:
            fields[field] = None

    data = PatientCreate(**fields)
    assert data.id_card == _ID, "身份证被手机号的错误连累丢掉了 → 复诊必重复建档"
    assert data.phone is None


def test_身份证脏数据不应连累手机号():
    fields = {"name": "王五", "gender": "女", "birth_date": None,
              "id_card": "12345", "phone": "13800138000"}

    for field in ("id_card", "phone"):
        probe = {**fields, "id_card": None, "phone": None, field: fields[field]}
        try:
            PatientCreate(**probe)
        except ValidationError:
            fields[field] = None

    data = PatientCreate(**fields)
    assert data.id_card is None
    assert data.phone == "13800138000", "手机号这个强键被白丢了"


# ── #18 手工初诊弱键不再静默合并 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_弱键关闭时同名同生日不会被误合并(async_db):
    """手工初诊路径现在传 allow_weak_match=False。

    此前默认 True，医生照着新病人念了姓名和生日，系统就把他挂到另一个同名同
    生日的人名下，并把**那个人的过敏史**预填进表单——按别人的过敏史开药可能
    致命。同名同生日在几万份档案里是必然会撞的。
    """
    from datetime import date

    await _make_patient(async_db, id_card=None, phone=None,
                        birth_date=date(1985, 3, 12))
    found = await PatientService(async_db).find_existing(
        name="张三", birth_date=date(1985, 3, 12), allow_weak_match=False
    )
    assert found is None, "弱键仍在静默复用别人的档案"


@pytest.mark.asyncio
async def test_弱键候选会被单独列出供医生确认(async_db):
    """不静默合并，但也不能装作查不到——候选人要交给医生人眼确认。"""
    from datetime import date

    pid = await _make_patient(async_db, id_card=None, phone=None,
                              birth_date=date(1985, 3, 12))
    cands = await PatientService(async_db).find_weak_candidates(
        name="张三", birth_date=date(1985, 3, 12)
    )
    assert [c["id"] for c in cands] == [pid]


@pytest.mark.asyncio
async def test_缺姓名或生日时不返回候选(async_db):
    """信息不全就别乱提示，否则弹框会变成噪音被医生无脑点掉。"""
    from datetime import date

    # id_card 置空：身份证内嵌 1949-12-31，与这里的 birth_date 冲突会被
    # _assert_id_card_birth_date_consistent 正确拦下（那是另一条防线，不是本例重点）
    await _make_patient(async_db, id_card=None, birth_date=date(1985, 3, 12))
    svc = PatientService(async_db)
    assert await svc.find_weak_candidates(name="张三", birth_date=None) == []
    assert await svc.find_weak_candidates(name=None, birth_date=date(1985, 3, 12)) == []
