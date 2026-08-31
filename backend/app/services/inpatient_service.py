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

from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.models.inpatient import ProblemItem, VitalSign
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.utils.age import calc_age


# ── 病区视图 ──────────────────────────────────────────────────────────────────

# 已出院但出院记录未签发时，接诊在病区列表里保留多久（天）
_DISCHARGED_PENDING_DAYS = 7


async def list_active_ward(db: AsyncSession, doctor_id: str) -> list[dict]:
    """返回当前医生负责的住院接诊列表（用于病区视图）。

    包含两类：
      1. 在院（status=in_progress）
      2. **已出院但出院记录还没签发**的（近 7 天内）

    第 2 类是 2026-08-14 第六轮审计修复：办理出院会把接诊置为 completed，
    而病区列表原先只查 in_progress——接诊当场从列表消失。可出院记录按规范是
    **出院后 24 小时内**完成，医生这时候已经没有任何入口进这个接诊补写了。
    保留到出院记录签发为止（最多 7 天，避免列表被历史堆满）。
    """
    discharge_cutoff = datetime.now() - timedelta(days=_DISCHARGED_PENDING_DAYS)

    # 已签发出院记录的接诊 id（这些不再需要留在列表里）
    discharged_done = select(MedicalRecord.encounter_id).where(
        MedicalRecord.record_type == "discharge_record",
        MedicalRecord.status == "submitted",
    )

    stmt = (
        select(Encounter, Patient)
        .join(Patient, Encounter.patient_id == Patient.id)
        .where(
            Encounter.doctor_id == doctor_id,
            Encounter.visit_type == "inpatient",
            or_(
                Encounter.status == "in_progress",
                and_(
                    Encounter.status == "completed",
                    # 按**出院时刻**算保留窗口（2026-08-14 第八轮审计修复）：
                    # 原先写的是 visited_at（入院时刻）——住 30 天的患者出院时
                    # visited_at 已是 29 天前，这个条件恒不成立，接诊当场从
                    # 病区列表消失。而住院端唯一的接诊入口就是这个列表
                    # （出院后 currentPatient 被 resetAllWorkbench 清空），
                    # 医生再也点不进去，规范要求的「出院后 24 小时内完成出院
                    # 记录」直接没有入口——正是本函数注释声称修好的那个问题。
                    # 住得越久越必然踩中，短住院（≤7 天）测试全绿，所以没被发现。
                    # completed_at 兜底用 visited_at：极老数据可能没有该字段。
                    func.coalesce(Encounter.completed_at, Encounter.visited_at)
                    >= discharge_cutoff,
                    Encounter.id.not_in(discharged_done),
                ),
            ),
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
            # 供前端区分展示：已出院的这条是"待补出院记录"，不是在院病人
            "encounter_status": enc.status,
            "pending_discharge_record": enc.status == "completed",
        }
        for enc, pat in rows
    ]


# ── 生命体征 ──────────────────────────────────────────────────────────────────

def _parse_recorded_at(raw: Optional[str]) -> datetime:
    """解析前端传的 ISO 时间，失败回退当前时间。

    时区归一（2026-08-11 审计修复）：带时区的输入先 astimezone() 换算到服务器本地
    时间（生产 TZ=Asia/Shanghai）再剥 tzinfo，与 parse_iso_naive 口径一致；
    原实现直接 replace(tzinfo=None) 会把 UTC 值当北京值存，落库差 8 小时。
    """
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
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

async def _lock_encounter(db: AsyncSession, encounter_id: str) -> None:
    """锁接诊行，串行化同一接诊的主要诊断互斥写（2026-08-31 并发矩阵审计）。

    ProblemItem 的"同接诊只能有一条 is_primary"此前既无锁也无 DB 约束：
    读-清零-插新全程裸奔，READ COMMITTED 下两个并发"设为主要"各自看不到
    对方刚插的行，结果两条都是主要诊断。对照 diagnoses 表的同一不变量——
    既有接诊行锁（diagnosis_service.replace_all）又有部分唯一索引
    uq_diag_primary_per_enc，这里两样都没有。锁序与全仓一致（encounter 在前）。
    """
    from app.models.encounter import Encounter

    await db.execute(
        select(Encounter.id).where(Encounter.id == encounter_id).with_for_update()
    )


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
        await _lock_encounter(db, encounter_id)
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
    if is_primary:
        # 同 add_problem：设为主要诊断前先锁接诊行串行化互斥写
        await _lock_encounter(db, encounter_id)
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
