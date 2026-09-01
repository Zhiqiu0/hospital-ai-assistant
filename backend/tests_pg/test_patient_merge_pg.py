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
from app.models.user import User
from app.services import patient_merge_service as svc


def _session_factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _mk_operator(db) -> str:
    """建一个真实操作者账号。

    patients.deleted_by 有外键指向 users——真 PG 强制它，而 tests/ 用的 SQLite
    默认不开外键检查，随手传个 "admin" 字符串在那边一路绿灯。这类只在真库上
    炸的约束正是本目录存在的理由。
    """
    uid = str(uuid.uuid4())
    db.add(User(id=uid, username=f"op_{uid[:8]}", password_hash="x",
                real_name="数据管理员", role="admin"))
    await db.flush()
    return uid


async def test_合并时身份证补空不撞唯一索引(alembic_pg):
    """target 没身份证、source 有——这正是重复档案最典型的形态：
    第一次挂号老人没带身份证（建了无证档案），第二次带了（建了有证档案）。"""
    Session = _session_factory(alembic_pg)
    tid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    id_card = "330523194001011234"

    async with Session() as db:
        operator = await _mk_operator(db)
        db.add_all([
            Patient(id=tid, name="王大爷", gender="male"),
            Patient(id=sid, name="王大爷", gender="male", id_card=id_card,
                    birth_date=date(1940, 1, 1),
                    profile_allergy_history="头孢过敏"),
        ])
        await db.commit()

    async with Session() as db:
        await svc.merge(db, target_id=tid, source_id=sid,
                        confirm_name="王大爷", operator_id=operator)

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
        operator = await _mk_operator(db)
        db.add_all([
            Patient(id=tid, name="李奶奶", gender="female"),
            Patient(id=sid, name="李奶奶", gender="female"),
        ])
        await db.flush()
        db.add(Encounter(patient_id=sid, doctor_id=operator,
                         visit_type="outpatient"))
        await db.commit()

    async with Session() as db:
        res = await svc.merge(db, target_id=tid, source_id=sid,
                              confirm_name="李奶奶", operator_id=operator)
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


async def test_过敏史真的被合并过来(alembic_pg):
    """档案纵向字段的真实存储是 patients.profile 这个 JSONB 列。

    2026-09-02 生产实测抓到：合并原本只搬 profile_allergy_history 等**旧扁平
    列**——那是 JSONB 重构后就没有任何代码再写的字段（生产 70 份档案里仅 1 份
    还留着重构前的残值，而 JSONB 里有值的是 13 份）。于是合并对真实档案数据
    完全无效：过敏史、既往史全留在被软删掉的 source 上。

    后果比不合并更糟——合并前医生在两份档案里各能看到一半，合并后 source 一
    软删，它那一半直接从视野里消失。而「过敏史分散在两份档案下，医生只看得到
    一半」正是这个功能存在的唯一理由。
    """
    Session = _session_factory(alembic_pg)
    tid, sid = str(uuid.uuid4()), str(uuid.uuid4())

    async with Session() as db:
        operator = await _mk_operator(db)
        db.add_all([
            # target 只有既往史，没有过敏史
            Patient(id=tid, name="陈大爷", gender="male", profile={
                "past_history": {"value": "高血压10年", "updated_at": "2026-08-01T09:00:00",
                                 "updated_by": "doc-a"},
            }),
            # source 有过敏史——合并后必须出现在 target 上
            Patient(id=sid, name="陈大爷", gender="male", profile={
                "allergy_history": {"value": "头孢过敏，用药前务必核对",
                                    "updated_at": "2026-08-20T14:30:00",
                                    "updated_by": "doc-b"},
                "past_history": {"value": "（这条不该覆盖 target 已有的）",
                                 "updated_at": "2026-08-20T14:30:00", "updated_by": "doc-b"},
            }),
        ])
        await db.commit()

    async with Session() as db:
        res = await svc.merge(db, target_id=tid, source_id=sid,
                              confirm_name="陈大爷", operator_id=operator)
        assert "allergy_history" in res["filled_fields"]

    async with Session() as db:
        t = await db.get(Patient, tid)
        allergy = (t.profile or {}).get("allergy_history") or {}
        assert allergy.get("value") == "头孢过敏，用药前务必核对", "过敏史没被合并过来"
        # 溯源信息要一起搬：档案上每个字段是谁什么时候确认的，合并后仍要能追
        assert allergy.get("updated_by") == "doc-b"
        assert allergy.get("updated_at") == "2026-08-20T14:30:00"
        # 补空不覆盖：target 已确认过的既往史不能被 source 悄悄改掉
        assert (t.profile["past_history"])["value"] == "高血压10年"


async def test_预览页能看见过敏史(alembic_pg):
    """预览是执行合并前唯一的人眼防线。原实现读的是已废弃的扁平列，两份档案的
    过敏史一律显示为空——操作员看不见「这份档案有过敏史」，也就无从发现合并
    把它搬丢了。"""
    Session = _session_factory(alembic_pg)
    tid, sid = str(uuid.uuid4()), str(uuid.uuid4())

    async with Session() as db:
        await _mk_operator(db)
        db.add_all([
            Patient(id=tid, name="周奶奶", gender="female"),
            Patient(id=sid, name="周奶奶", gender="female", profile={
                "allergy_history": {"value": "青霉素过敏", "updated_at": None,
                                    "updated_by": None},
            }),
        ])
        await db.commit()

    async with Session() as db:
        prev = await svc.preview(db, target_id=tid, source_id=sid)
        assert prev["source"]["allergy_history"] == "青霉素过敏",             "预览看不到源档案的过敏史，人眼防线形同虚设"
