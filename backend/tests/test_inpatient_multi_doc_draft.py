"""住院第 2 份起同类型文书的草稿落库（2026-08-14 第八轮审计 high）。

复现的是审计员实跑出来的场景：

    8/2 医生写第 1 份日常病程并签发（record_no=1）
    8/3 写第 2 份：每 5 秒的 auto-save 按 (encounter_id, record_type) 取到那份
        已签发的 record_no=1 → 直接 403「病历已签发，不可再编辑」
        而前端 useAutoSaveDraft 把 403 判为「永久性拒绝」，清空失败队列并提示
        「该病历已签发，草稿不再自动保存」
    → 此后整段住院期间该类型的草稿**一个字都不落库**，只有签发那一刻有数据。
    AI 一键生成走 save_ai_draft 同样返回 saved=False，而调用方不检查返回值，
    生成的第 2 份病程只活在浏览器 store 里。

住院 30 天 15 份病程 + 3 份查房，除第一份外中途关标签页/掉线即全丢——
而 auto-save 存在的理由正是防这个。
"""

from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.services.medical_record_service import MedicalRecordService


async def _seed(db, visit_type: str = "inpatient") -> None:
    db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-1",
        visit_type=visit_type, status="in_progress",
        visited_at=datetime(2026, 8, 1),
    ))
    await db.flush()


async def _sign(db, svc, record_type: str, text: str):
    """签发当前这份同类型文书。"""
    return await svc.quick_save(
        encounter_id="enc-1", record_type=record_type,
        content=text, doctor_id="doc-1",
    )


@pytest.mark.asyncio
async def test_住院第二份病程的autosave不再被403(async_db):
    """核心断言：签发第 1 份后，第 2 份的 auto-save 必须能落库。"""
    await _seed(async_db)
    svc = MedicalRecordService(async_db)

    await svc.auto_save_draft("enc-1", "course_record", "8月2日病程", "doc-1")
    await _sign(async_db, svc, "course_record", "8月2日病程 定稿")

    # 8/3 写第二份 —— 修复前这里抛 403
    res = await svc.auto_save_draft("enc-1", "course_record", "8月3日病程写到一半", "doc-1")
    assert res["record_id"], "第二份病程的 auto-save 没落库"

    rows = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.record_type == "course_record")
    )).scalars().all()
    assert len(rows) == 2, f"应有两份同类型文书，实际 {len(rows)}"
    assert sorted(r.record_no for r in rows) == [1, 2], "record_no 没有正确递增"


@pytest.mark.asyncio
async def test_住院第二份的AI草稿不再被静默丢弃(async_db):
    """save_ai_draft 原先返回 saved=False，而调用方不检查返回值也不报错。"""
    await _seed(async_db)
    svc = MedicalRecordService(async_db)

    await svc.save_ai_draft("enc-1", "course_record", "AI 生成的第一份", "doc-1")
    await _sign(async_db, svc, "course_record", "第一份 定稿")

    res = await svc.save_ai_draft("enc-1", "course_record", "AI 生成的第二份", "doc-1")
    assert res["saved"] is True, "AI 生成的第二份病程被静默丢弃"


@pytest.mark.asyncio
async def test_连续多份病程各自独立落库(async_db):
    """住院 30 天的真实形态：一份接一份，每份都要有自己的草稿。"""
    await _seed(async_db)
    svc = MedicalRecordService(async_db)

    for day in range(1, 6):
        await svc.auto_save_draft("enc-1", "course_record", f"第{day}天病程", "doc-1")
        await _sign(async_db, svc, "course_record", f"第{day}天病程 定稿")

    rows = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.record_type == "course_record")
    )).scalars().all()
    assert len(rows) == 5
    assert sorted(r.record_no for r in rows) == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_门诊已签发仍然不可再编辑(async_db):
    """防过度放开：门急诊一次接诊一份病历，已签发就是真的不能改。"""
    await _seed(async_db, visit_type="outpatient")
    svc = MedicalRecordService(async_db)

    await svc.auto_save_draft("enc-1", "outpatient", "门诊病历", "doc-1")
    await _sign(async_db, svc, "outpatient", "门诊病历 定稿")

    with pytest.raises(HTTPException) as exc:
        await svc.auto_save_draft("enc-1", "outpatient", "签发后又改", "doc-1")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_门诊已签发时AI草稿仍然跳过(async_db):
    await _seed(async_db, visit_type="outpatient")
    svc = MedicalRecordService(async_db)

    await svc.save_ai_draft("enc-1", "outpatient", "AI 门诊草稿", "doc-1")
    await _sign(async_db, svc, "outpatient", "门诊病历 定稿")

    res = await svc.save_ai_draft("enc-1", "outpatient", "签发后 AI 又生成", "doc-1")
    assert res["saved"] is False


# ── 出院后补写窗口按出院时刻算（第八轮审计 high）──────────────────────────────

@pytest.mark.asyncio
async def test_长期住院出院后仍留在病区列表(async_db):
    """住 30 天的患者出院后，医生必须还能进去补写出院记录。

    原实现按 visited_at（入院时刻）算 7 天窗口——住 30 天的患者 visited_at
    是 29 天前，条件恒不成立，接诊当场从病区列表消失。而住院端唯一的接诊入口
    就是这个列表，医生再也点不进去，规范要求的「出院后 24 小时内完成出院记录」
    直接没有入口。住得越久越必然踩中，短住院测试全绿所以一直没被发现。
    """
    from datetime import timedelta
    from app.services.inpatient_service import list_active_ward

    now = datetime.now()
    async_db.add(Patient(id="p-long", name="李四", birth_date=date(1960, 1, 1)))
    async_db.add(Encounter(
        id="enc-long", patient_id="p-long", doctor_id="doc-1",
        visit_type="inpatient", status="completed",
        visited_at=now - timedelta(days=30),   # 30 天前入院
        completed_at=now - timedelta(hours=2),  # 2 小时前出院
    ))
    await async_db.commit()

    rows = await list_active_ward(async_db, "doc-1")
    assert any(r["encounter_id"] == "enc-long" for r in rows), \
        "住 30 天的患者出院后从病区列表消失了，无法补写出院记录"


@pytest.mark.asyncio
async def test_出院超过保留期才移出列表(async_db):
    """防过度放开：出院很久的接诊不该一直堆在病区列表里。"""
    from datetime import timedelta
    from app.services.inpatient_service import list_active_ward

    now = datetime.now()
    async_db.add(Patient(id="p-old", name="王五", birth_date=date(1960, 1, 1)))
    async_db.add(Encounter(
        id="enc-old", patient_id="p-old", doctor_id="doc-1",
        visit_type="inpatient", status="completed",
        visited_at=now - timedelta(days=40),
        completed_at=now - timedelta(days=10),  # 10 天前出院，超出 7 天保留期
    ))
    await async_db.commit()

    rows = await list_active_ward(async_db, "doc-1")
    assert not any(r["encounter_id"] == "enc-old" for r in rows)


@pytest.mark.asyncio
async def test_save_ai_draft返回落库时间供前端同步乐观锁基线(async_db):
    """2026-08-21 第四轮走查：AI 生成落库后前端 auto-save 基线不知道这次写入，
    下一次保存拿旧基线必假 409。done 事件带 updated_at 的前提是这里返回它。"""
    await _seed(async_db)
    svc = MedicalRecordService(async_db)

    res = await svc.save_ai_draft("enc-1", "course_record", "AI 生成的病程", "doc-1")
    assert res["saved"] is True
    assert res.get("updated_at"), "save_ai_draft 必须返回落库 updated_at"
    # 前端拿这个基线做下一次 auto-save 的乐观锁凭证，必须通过校验（不假 409）
    from datetime import datetime as _dt
    baseline = _dt.fromisoformat(res["updated_at"])
    res2 = await svc.auto_save_draft(
        "enc-1", "course_record", "医生接着改了一句", "doc-1",
        expected_updated_at=baseline,
    )
    assert res2["record_id"], "带 save_ai_draft 返回的基线保存被误判为冲突"
