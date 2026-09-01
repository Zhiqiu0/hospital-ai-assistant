# -*- coding: utf-8 -*-
"""重复档案合并在**真 PG** 上的行为（2026-09-02 数据更正流程实测）。

为什么必须在真 PG 上测：合并会把 source 的身份证补给 target，同时把 source
软删。身份证的唯一性由部分索引 uq_patients_id_card_active 保证——

    UNIQUE (id_card) WHERE id_card IS NOT NULL AND is_deleted = false

两行在同一个事务里一改一删，谁先落盘决定会不会出现「两行同时带同一身份证且
都 is_deleted=false」的瞬间。SQLAlchemy 对同一 mapper 的多个脏对象不保证
UPDATE 顺序，而 PG 的唯一索引是**每条语句后**检查的。SQLite 的约束时机与
PG 不同，tests/ 那边跑绿说明不了 PG 上的事。

合并不可逆且开业第一周就要用（老人无身份证、儿童留家长手机会产生重复档案），
在这里挂 500 意味着数据搬到一半失败回滚，操作员只看到一个红叉。
"""
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.encounter import Encounter
from app.models.patient import Patient
from app.services import patient_merge_service as svc


def _session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_合并时身份证补空不撞唯一索引(alembic_pg):
    """target 没身份证、source 有——这正是重复档案最典型的形态：
    第一次挂号老人没带身份证（建了无证档案），第二次带了（建了有证档案）。"""
    Session = _session_factory(alembic_pg)
    tid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    id_card = "330523194001011234"

    async with Session() as db:
        db.add_all([
            Patient(id=tid, name="王大爷", gender="male"),
            Patient(id=sid, name="王大爷", gender="male", id_card=id_card,
                    birth_date=date(1940, 1, 1),
                    profile_allergy_history="头孢过敏"),
        ])
        await db.commit()

    async with Session() as db:
        await svc.merge(db, target_id=tid, source_id=sid,
                        confirm_name="王大爷", operator_id="admin")

    async with Session() as db:
        t = await db.get(Patient, tid)
        s = await db.get(Patient, sid)
        assert t.id_card == id_card, "身份证没搬过去"
        # 过敏史是合并的核心临床价值：分散在两份档案下时，开药前的飘红警示
        # 只看得到一半
        assert t.profile_allergy_history == "头孢过敏"
        assert s.is_deleted is True and s.merged_into == tid


async def test_接诊与档案一起搬且源档案退出查重(alembic_pg):
    """搬完接诊后，source 必须退出「活跃档案」集合，否则下次挂号又查到它。"""
    Session = _session_factory(alembic_pg)
    tid, sid = str(uuid.uuid4()), str(uuid.uuid4())

    async with Session() as db:
        db.add_all([
            Patient(id=tid, name="李奶奶", gender="female"),
            Patient(id=sid, name="李奶奶", gender="female"),
        ])
        await db.flush()
        db.add(Encounter(patient_id=sid, doctor_id="doc-1",
                         visit_type="outpatient"))
        await db.commit()

    async with Session() as db:
        res = await svc.merge(db, target_id=tid, source_id=sid,
                              confirm_name="李奶奶", operator_id="admin")
        assert res["moved"]["encounters"] == 1

    async with Session() as db:
        moved = (await db.execute(
            select(Encounter).where(Encounter.patient_id == tid)
        )).scalars().all()
        assert len(moved) == 1, "接诊没搬到目标档案下"
        active = (await db.execute(
            select(Patient).where(Patient.name == "李奶奶",
                                  Patient.is_deleted == False)  # noqa: E712
        )).scalars().all()
        assert len(active) == 1, "源档案没退出活跃集合，下次挂号还会查到它"
