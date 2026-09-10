# -*- coding: utf-8 -*-
"""visit_no 部分唯一索引（2026-09-10 收敛轮并发审计）。

visit_no 是 HIS 接诊幂等真键，此前去重只靠 advisory lock + 应用层查重，
无数据库兜底。这里验证模型声明的部分唯一索引真的生效（SQLite 3.45 支持
部分索引，测试库与 PG 语义一致）：
  · 同 visit_no 第二条插入必须被数据库拒绝；
  · visit_no 为 NULL（手动接诊）不受约束，可以任意多条；
  · 已取消的接诊不挡道：HIS 重推同 visit_no 能建新接诊（业务规则，
    test_admit_cancelled_encounter_not_reused 的口径）。
"""
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.encounter import Encounter
from app.models.patient import Patient


async def _mk_patient(db) -> str:
    p = Patient(name="幂等键", gender="male")
    db.add(p)
    await db.flush()
    return p.id


@pytest.mark.asyncio
async def test_同visit_no第二条插入被数据库拒绝(async_db):
    pid = await _mk_patient(async_db)
    async_db.add(Encounter(patient_id=pid, doctor_id="doc-1", visit_type="outpatient",
                           visited_at=datetime.now(), visit_no="V20260910-001"))
    await async_db.commit()

    async_db.add(Encounter(patient_id=pid, doctor_id="doc-2", visit_type="outpatient",
                           visited_at=datetime.now(), visit_no="V20260910-001"))
    with pytest.raises(IntegrityError):
        await async_db.commit()
    await async_db.rollback()


@pytest.mark.asyncio
async def test_手动接诊visit_no为NULL不受约束(async_db):
    pid = await _mk_patient(async_db)
    for doc in ("doc-1", "doc-2"):
        async_db.add(Encounter(patient_id=pid, doctor_id=doc, visit_type="outpatient",
                               visited_at=datetime.now(), visit_no=None))
    await async_db.commit()  # 两条 NULL 并存不冲突


@pytest.mark.asyncio
async def test_已取消接诊不阻断同visit_no重建(async_db):
    """医生误建后取消，HIS 患者重新叫号推送同 visit_no——必须能建新接诊。"""
    pid = await _mk_patient(async_db)
    async_db.add(Encounter(patient_id=pid, doctor_id="doc-1", visit_type="outpatient",
                           visited_at=datetime.now(), visit_no="V20260910-002",
                           status="cancelled"))
    await async_db.commit()

    async_db.add(Encounter(patient_id=pid, doctor_id="doc-1", visit_type="outpatient",
                           visited_at=datetime.now(), visit_no="V20260910-002"))
    await async_db.commit()  # 不得抛 IntegrityError
