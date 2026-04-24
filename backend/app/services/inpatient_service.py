"""
住院专项业务服务（services/inpatient_service.py）

抽出原 `api/v1/inpatient.py` 路由里的 SQL 与业务规则，路由层只负责：
  - 解析请求
  - 鉴权（assert_encounter_access / admin role）
  - 调本层函数
  - 组装响应

本层提供：
  - list_active_ward(db, doctor_id)        病区视图：该医生的活跃住院接诊
  - record_vital_sign(db, ...)             录一次体征
  - list_vitals(db, encounter_id, limit?)  读体征历史
  - latest_vital(db, encounter_id)         最新一次体征
  - add_problem(db, ...)                   新增问题（含主要诊断互斥处理）
  - list_problems(db, encounter_id)        读问题列表
  - update_problem(db, ...)                更新问题
  - delete_problem(db, encounter_id, pid)  删除问题
  - compute_compliance(db, encounter_id, rules)  时效合规检查

所有序列化（to_dict）保留在路由层，由路由决定对外形状；
本层只返回 ORM 对象或纯数据，不耦合 HTTP。
"""

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.models.inpatient import ProblemItem, VitalSign
from app.models.patient import Patient
from app.utils.age import calc_age


# ── 病区视图 ──────────────────────────────────────────────────────────────────

async def list_active_ward(db: AsyncSession, doctor_id: str) -> list[dict]:
    """返回当前医生负责的活跃住院接诊列表（用于病区视图）。"""
    stmt = (
        select(Encounter, Patient)
        .join(Patient, Encounter.patient_id == Patient.id)
        .where(
            Encounter.doctor_id == doctor_id,
            Encounter.visit_type == "inpatient",
            Encounter.status == "in_progress",
        )
        .order_by(Encounter.visited_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    # Patient 表无 age 字段，统一走 utils.calc_age 由 birth_date 实时算
    return [
        {
            "encounter_id": enc.id,
            "patient_id": pat.id,
            "patient_name": pat.name,
            "gender": pat.gender,
            "age": calc_age(pat.birth_date),
            "bed_no": enc.bed_no,
            "admission_route": enc.admission_route,
            "admission_condition": enc.admission_condition,
            "visited_at": enc.visited_at.isoformat() if enc.visited_at else None,
            "chief_complaint": enc.chief_complaint_brief,
        }
        for enc, pat in rows
    ]


# ── 生命体征 ──────────────────────────────────────────────────────────────────

def _parse_recorded_at(raw: Optional[str]) -> datetime:
    """解析前端传的 ISO 时间，失败回退当前时间。"""
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.now()


async def record_vital_sign(
    db: AsyncSession,
    *,
    encounter_id: str,
    recorded_at_raw: Optional[str],
    fields: dict,
    recorded_by: str,
) -> VitalSign:
    """录入一次生命体征；调用方已做 encounter 权限校验。"""
    sign = VitalSign(
        encounter_id=encounter_id,
        recorded_at=_parse_recorded_at(recorded_at_raw),
        recorded_by=recorded_by,
        **fields,
    )
    db.add(sign)
    await db.commit()
    await db.refresh(sign)
    return sign


async def list_vitals(db: AsyncSession, encounter_id: str) -> list[VitalSign]:
    stmt = (
        select(VitalSign)
        .where(VitalSign.encounter_id == encounter_id)
        .order_by(VitalSign.recorded_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def latest_vital(db: AsyncSession, encounter_id: str) -> Optional[VitalSign]:
    stmt = (
        select(VitalSign)
        .where(VitalSign.encounter_id == encounter_id)
        .order_by(VitalSign.recorded_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalars().first()


# ── 问题列表 ──────────────────────────────────────────────────────────────────

async def _clear_primary_flags(db: AsyncSession, encounter_id: str, *, exclude_id: Optional[str] = None) -> None:
    """清除同一接诊下其他问题的 is_primary 标记（可选排除某条）。"""
    conds = [ProblemItem.encounter_id == encounter_id, ProblemItem.is_primary.is_(True)]
    if exclude_id:
        conds.append(ProblemItem.id != exclude_id)
    result = await db.execute(select(ProblemItem).where(*conds))
    for old in result.scalars().all():
        old.is_primary = False


async def add_problem(
    db: AsyncSession,
    *,
    encounter_id: str,
    problem_name: str,
    icd_code: Optional[str],
    onset_date: Optional[str],
    is_primary: bool,
    added_by: str,
) -> ProblemItem:
    """新增一条问题/诊断；若标为主要诊断，清除同接诊其他主要诊断标记。"""
    if is_primary:
        await _clear_primary_flags(db, encounter_id)

    item = ProblemItem(
        encounter_id=encounter_id,
        problem_name=problem_name,
        icd_code=icd_code,
        onset_date=onset_date,
        is_primary=is_primary,
        added_by=added_by,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def list_problems(db: AsyncSession, encounter_id: str) -> list[ProblemItem]:
    stmt = (
        select(ProblemItem)
        .where(ProblemItem.encounter_id == encounter_id)
        .order_by(ProblemItem.is_primary.desc(), ProblemItem.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def update_problem(
    db: AsyncSession,
    *,
    encounter_id: str,
    problem_id: str,
    status: Optional[str],
    icd_code: Optional[str],
    is_primary: Optional[bool],
) -> ProblemItem:
    """更新问题状态/ICD/主要标记。"""
    result = await db.execute(
        select(ProblemItem).where(
            ProblemItem.id == problem_id,
            ProblemItem.encounter_id == encounter_id,
        )
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="问题条目不存在")

    if status is not None:
        item.status = status
    if icd_code is not None:
        item.icd_code = icd_code
    if is_primary is not None:
        if is_primary:
            await _clear_primary_flags(db, encounter_id, exclude_id=problem_id)
        item.is_primary = is_primary

    await db.commit()
    await db.refresh(item)
    return item


async def delete_problem(db: AsyncSession, encounter_id: str, problem_id: str) -> None:
    result = await db.execute(
        select(ProblemItem).where(
            ProblemItem.id == problem_id,
            ProblemItem.encounter_id == encounter_id,
        )
    )
    item = result.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="问题条目不存在")
    await db.delete(item)
    await db.commit()
