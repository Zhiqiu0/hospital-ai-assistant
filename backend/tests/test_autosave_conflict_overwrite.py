# -*- coding: utf-8 -*-
"""多设备冲突覆盖不得让内容永久消失（2026-09-01 多设备并发审计回归锁）。

场景：医生在诊室电脑和护士站电脑上同时开着同一份病历（医院常态）。落后的一方
撞 409 后会清空乐观锁基线继续保存——不这么做的话它后续输入永久不落库，那更糟。
但 auto-save 平时是 UPSERT 当前版本的 content，于是下一次 5 秒防抖把整段内容
**原地覆写**，另一端刚写的内容就此从库里彻底消失：赢的一方毫无提示，输的一方
也不知道自己盖掉了什么。

改为：带 force_overwrite 的那一次**另起一版**（与既有的"AI 版本冻结另起一版"
同构），被覆盖的内容留在旧版本行里。record_versions 只追加永不删除，最坏也只是
"要人工从版本历史里捞"，而不是永久丢失。

注：这只解决"数据还在不在"。要让医生自己看到并选择保留哪一版，需要冲突合并
交互 + 版本调取端点，那是另一件事。
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.services.medical_record_service import MedicalRecordService


async def _mk_encounter(db) -> str:
    patient = Patient(name="赵六", gender="female")
    db.add(patient)
    await db.flush()
    enc = Encounter(patient_id=patient.id, doctor_id="doc-1",
                    visit_type="outpatient", visited_at=datetime.now())
    db.add(enc)
    await db.commit()
    return enc.id


async def _versions(db, record_id: str) -> list[tuple[int, str]]:
    rows = (await db.execute(
        select(RecordVersion.version_no, RecordVersion.content)
        .where(RecordVersion.medical_record_id == record_id)
        .order_by(RecordVersion.version_no)
    )).all()
    return [(no, (c or {}).get("text", "")) for no, c in rows]


@pytest.mark.asyncio
async def test_强制覆盖时被盖掉的内容留在历史版本(async_db):
    svc = MedicalRecordService(async_db)
    enc_id = await _mk_encounter(async_db)

    # 护士站那台先写
    await svc.auto_save_draft(encounter_id=enc_id, record_type="outpatient",
                              content="护士站写的内容", user_id="doc-1")
    # 诊室那台撞 409 后带 force_overwrite 覆盖
    res = await svc.auto_save_draft(encounter_id=enc_id, record_type="outpatient",
                                    content="诊室写的内容", user_id="doc-1",
                                    force_overwrite=True)

    record = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.encounter_id == enc_id)
    )).scalar_one()
    texts = [t for _, t in await _versions(async_db, record.id)]

    assert "诊室写的内容" in texts, "覆盖方的内容没存下来"
    assert "护士站写的内容" in texts, "被覆盖的内容从库里消失了——这正是本次要修的"
    assert res["version_no"] == record.current_version == 2


@pytest.mark.asyncio
async def test_普通自动保存仍然不爆版本(async_db):
    """5 秒一次的高频 auto-save 必须继续原地 UPSERT，否则版本号会爆炸。"""
    svc = MedicalRecordService(async_db)
    enc_id = await _mk_encounter(async_db)

    for i in range(5):
        await svc.auto_save_draft(encounter_id=enc_id, record_type="outpatient",
                                  content=f"第 {i} 次输入", user_id="doc-1")

    record = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.encounter_id == enc_id)
    )).scalar_one()
    assert record.current_version == 1
    assert len(await _versions(async_db, record.id)) == 1


@pytest.mark.asyncio
async def test_内容没变时不因force而爆版本(async_db):
    """补发队列/重试可能带着同样的内容再来一次，不该平白多一版。"""
    svc = MedicalRecordService(async_db)
    enc_id = await _mk_encounter(async_db)

    await svc.auto_save_draft(encounter_id=enc_id, record_type="outpatient",
                              content="同样的内容", user_id="doc-1")
    await svc.auto_save_draft(encounter_id=enc_id, record_type="outpatient",
                              content="同样的内容", user_id="doc-1",
                              force_overwrite=True)

    record = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.encounter_id == enc_id)
    )).scalar_one()
    assert record.current_version == 1
