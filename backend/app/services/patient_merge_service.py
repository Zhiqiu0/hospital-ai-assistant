# -*- coding: utf-8 -*-
"""重复患者档案合并（services/patient_merge_service.py）

2026-09-01 数据更正流程审计新增。

**为什么必须有**：老人无身份证、儿童留家长手机、代挂号——三级查重强键
（身份证 / 院内主索引 / 手机号+姓名）全 miss 时系统会新建档案。这是刻意的
取舍，代码里三处注释写得很清楚：「宁可产生重复档案（可事后人工合并），
误合并两个人不可逆」。问题是**「可事后人工合并」这句话在三处注释里出现过，
而合并功能一直不存在**。

后果不是不好看，是临床风险：既往史/过敏史/影像/检验分散在两份档案下，医生
查复诊史只看得到一半——而过敏史正是开药前工作台飘红警示的那个字段。

**设计上的三条红线**：
  ① 不可逆 → 必须先干跑预览、执行时逐字确认源患者姓名（照抄清库脚本的确认
     短语机制）。误合并两个真实存在的人，比留着两份重复档案糟糕得多。
  ② 已签发病历的 patient_snapshot **绝不改动**。它签发瞬间冻结并进了
     sign_hash，是法定文书上的署名来源——签发时写的是哪个名字就永远是哪个。
     改它会让 verify_chain 把这份病历永久报为"内容被篡改"。
  ③ 档案字段只做"补空"不做"覆盖"：target 已有值一律保留，只有 target 为空
     而 source 有值时才搬过去。合并不该悄悄改掉医生已经确认过的过敏史。
"""
import datetime
import logging

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.models.imaging import ImagingStudy
from app.models.patient import Patient

logger = logging.getLogger(__name__)

# 档案类纵向字段：合并时按"补空不覆盖"规则处理
_PROFILE_FIELDS = (
    "profile_past_history", "profile_allergy_history", "profile_family_history",
    "profile_personal_history", "profile_current_medications",
    "profile_marital_history", "profile_menstrual_history", "profile_religion_belief",
)
# 身份类字段：同样只补空（target 是保留下来的那份，以它为准）
_IDENTITY_FIELDS = (
    "id_card", "phone", "address", "birth_date", "gender", "ethnicity",
    "marital_status", "occupation", "workplace", "contact_name",
    "contact_phone", "contact_relation", "blood_type", "patient_no",
)


async def _load(db: AsyncSession, patient_id: str, label: str) -> Patient:
    p = await db.get(Patient, patient_id)
    if p is None:
        raise HTTPException(404, f"{label}档案不存在")
    if p.is_deleted:
        raise HTTPException(400, f"{label}档案已被删除或已被合并过")
    return p


async def _counts(db: AsyncSession, patient_id: str) -> dict:
    """统计这份档案名下有多少数据——预览时给人眼判断用。"""
    enc = (await db.execute(
        select(func.count()).select_from(Encounter)
        .where(Encounter.patient_id == patient_id)
    )).scalar() or 0
    img = (await db.execute(
        select(func.count()).select_from(ImagingStudy)
        .where(ImagingStudy.patient_id == patient_id)
    )).scalar() or 0
    return {"encounters": enc, "imaging_studies": img}


def _brief(p: Patient) -> dict:
    """档案摘要，供预览时人眼比对"这两份到底是不是同一个人"。"""
    return {
        "id": p.id,
        "name": p.name,
        "gender": p.gender,
        "birth_date": p.birth_date.isoformat() if p.birth_date else None,
        "id_card": p.id_card,
        "phone": p.phone,
        "patient_no": p.patient_no,
        "allergy_history": p.profile_allergy_history,
    }


async def preview(db: AsyncSession, *, target_id: str, source_id: str) -> dict:
    """干跑：把两份档案与将要搬动的数据量摆出来，不做任何修改。

    这是执行前唯一的人眼防线——出生日期差得远、身份证都有且不同，就说明
    这是两个人，**立刻停手**。
    """
    if target_id == source_id:
        raise HTTPException(400, "源档案与目标档案是同一份")
    target = await _load(db, target_id, "目标")
    source = await _load(db, source_id, "源")

    warnings: list[str] = []
    if target.id_card and source.id_card and target.id_card != source.id_card:
        warnings.append("两份档案的身份证号都存在且不一致——极可能是两个不同的人")
    if (target.gender and source.gender and target.gender != source.gender
            and "unknown" not in (target.gender, source.gender)):
        warnings.append("性别不一致")
    if target.birth_date and source.birth_date and target.birth_date != source.birth_date:
        warnings.append("出生日期不一致")
    if target.name != source.name:
        warnings.append(f"姓名不一致：{target.name} / {source.name}")

    return {
        "target": _brief(target),
        "source": _brief(source),
        "will_move": await _counts(db, source_id),
        "warnings": warnings,
        "confirm_hint": f"执行合并需逐字输入源档案姓名「{source.name}」以确认",
    }


async def merge(db: AsyncSession, *, target_id: str, source_id: str,
                confirm_name: str, operator_id: str) -> dict:
    """把 source 合并进 target：数据搬家 + 档案补空 + source 软删。

    Args:
        confirm_name: 操作者逐字输入的源档案姓名，不匹配直接拒绝——合并不可逆，
            这道确认是防误点的最后一关（与开业清库脚本的确认短语同一思路）。

    Returns:
        搬动明细，供路由层写审计。
    """
    if target_id == source_id:
        raise HTTPException(400, "源档案与目标档案是同一份")
    # 行锁：两份档案都锁住再动，避免并发下另一个请求同时把 source 合并到别处
    target = await db.get(Patient, target_id, with_for_update=True)
    source = await db.get(Patient, source_id, with_for_update=True)
    if target is None or source is None:
        raise HTTPException(404, "档案不存在")
    if target.is_deleted or source.is_deleted:
        raise HTTPException(400, "档案已被删除或已被合并过")
    if (confirm_name or "").strip() != source.name:
        raise HTTPException(
            400,
            f"确认姓名不匹配：需逐字输入源档案姓名「{source.name}」。"
            "合并不可逆，误合并两个人无法撤销。",
        )

    moved = await _counts(db, source_id)

    # 搬之前先记下要搬哪些接诊、归属哪些医生——搬完就查不到了，而这两份
    # 名单是下面失效缓存用的（见函数末尾）。
    moving_rows = (await db.execute(
        select(Encounter.id, Encounter.doctor_id)
        .where(Encounter.patient_id == source_id)
    )).all()

    # ① 数据搬家：只有 encounters / imaging_studies 直接挂 patient_id，
    #    病历/检验/语音都经 encounter 关联，搬了接诊它们自然跟过去。
    await db.execute(
        update(Encounter).where(Encounter.patient_id == source_id)
        .values(patient_id=target_id)
    )
    await db.execute(
        update(ImagingStudy).where(ImagingStudy.patient_id == source_id)
        .values(patient_id=target_id)
    )

    # ② source 先软删并**立即 flush**，然后才能补空——顺序不能反。
    #
    #    2026-09-02 真 PG 用例抓到：身份证的唯一性由部分索引保证——
    #        uq_patients_id_card_active UNIQUE (id_card)
    #        WHERE id_card IS NOT NULL AND is_deleted = false
    #    补空若排在前面，SQLAlchemy 会先 UPDATE target 把 source 的身份证写上，
    #    而此刻 source 还是 is_deleted=false，两行同时活跃持有同一个身份证，
    #    PG 在这条语句后就判唯一冲突，整个合并 500 回滚。
    #    而这恰恰是最典型的重复档案形态：老人第一次挂号没带身份证（建了无证
    #    档案），第二次带了（建了有证档案）——正是这个功能要合的那种。
    #    SQLite 不检查部分索引的这个瞬间态，tests/ 那边一路绿灯。
    #
    #    **不动任何已签发病历的 patient_snapshot**——那是签发瞬间冻结、进了
    #    sign_hash 的法定署名，改它等于篡改法律文书。
    source.is_deleted = True
    source.deleted_at = datetime.datetime.now()
    source.deleted_by = operator_id
    source.merged_into = target_id
    await db.flush()

    # ③ 档案补空（不覆盖）：target 是保留下来的那份，以它为准；
    #    只有它没填而 source 填了的字段才搬过去。
    filled: list[str] = []
    for field in _IDENTITY_FIELDS + _PROFILE_FIELDS:
        if getattr(target, field, None) in (None, "") and getattr(source, field, None):
            setattr(target, field, getattr(source, field))
            filled.append(field)

    await db.commit()

    # ④ 失效缓存（2026-09-02 数据更正流程实测补）。原实现落库后什么都不清，
    #    而全仓其他改患者/接诊的路径（_patient_write / _patient_profile /
    #    _encounter_cancel / discharge）都清。三处都会读到脏数据，其中第一处
    #    直接废掉这个功能存在的理由：
    #      · target 的档案缓存——合并刚把 source 的过敏史补进 target，而工作台
    #        开药前的飘红警示读的就是这份缓存。不清则医生看到的仍是那份没有
    #        过敏史的旧档案，合并等于没做。
    #      · 被搬走的每条接诊的工作台快照——快照里带着患者信息，不清则那条
    #        接诊仍显示已被合并掉的旧档案。
    #      · 相关医生的「我的进行中接诊」列表——同理。
    #    source 自身的缓存一并清掉，避免已合并的档案还能从缓存里被查出来。
    from app.services.encounter_cache import (
        invalidate_encounter_snapshot,
        invalidate_my_encounters,
    )
    from app.services.patient_cache import _invalidate_patient_cache

    await _invalidate_patient_cache(target_id)
    await _invalidate_patient_cache(source_id)
    for enc_id, _doc_id in moving_rows:
        await invalidate_encounter_snapshot(enc_id)
    for doctor_id in {d for _e, d in moving_rows if d}:
        await invalidate_my_encounters(doctor_id)

    logger.warning(
        "patient.merge: source=%s -> target=%s 接诊%d 影像%d 补空字段%d 操作人=%s",
        source_id, target_id, moved["encounters"], moved["imaging_studies"],
        len(filled), operator_id,
    )
    return {
        "target_id": target_id,
        "source_id": source_id,
        "source_name": source.name,
        "moved": moved,
        "filled_fields": filled,
    }
