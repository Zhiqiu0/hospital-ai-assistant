"""
住院专项 API 路由（api/v1/inpatient.py）

端点列表：
  GET    /inpatient/ward                         - 病区视图：当前医生的活跃住院接诊列表
  POST   /encounters/{id}/vitals                 - 录入生命体征
  GET    /encounters/{id}/vitals                 - 获取体征历史
  GET    /encounters/{id}/vitals/latest          - 获取最新一次体征
  POST   /encounters/{id}/problems               - 新增问题/诊断
  GET    /encounters/{id}/problems               - 获取问题列表
  PATCH  /encounters/{id}/problems/{pid}         - 更新问题状态
  DELETE /encounters/{id}/problems/{pid}         - 删除问题
  GET    /encounters/{id}/compliance             - 时效合规检查
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.authz import assert_encounter_access
from app.database import get_db
from app.models.encounter import Encounter
from app.models.inpatient import ProblemItem, VitalSign
from app.models.medical_record import MedicalRecord
from app.services import inpatient_service

router = APIRouter()


# ── Request / Response 模型 ───────────────────────────────────────────────────

class VitalSignIn(BaseModel):
    """录入生命体征请求体。"""
    recorded_at: Optional[str] = None   # ISO8601 字符串，留空则用服务器当前时间
    temperature: Optional[float] = None
    pulse: Optional[int] = None
    respiration: Optional[int] = None
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    spo2: Optional[int] = None
    weight: Optional[float] = None
    height: Optional[float] = None
    notes: Optional[str] = None


class ProblemIn(BaseModel):
    """新增问题请求体。"""
    problem_name: str
    icd_code: Optional[str] = None
    onset_date: Optional[str] = None
    is_primary: bool = False


class ProblemPatch(BaseModel):
    """更新问题状态请求体。"""
    status: Optional[str] = None     # active / resolved
    is_primary: Optional[bool] = None
    icd_code: Optional[str] = None


# ── 病区视图 ──────────────────────────────────────────────────────────────────

@router.get("/inpatient/ward")
async def get_ward_view(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """返回当前医生负责的活跃住院接诊列表（用于病区视图）。"""
    items = await inpatient_service.list_active_ward(db, current_user.id)
    return {"items": items}


# ── 生命体征 ──────────────────────────────────────────────────────────────────

@router.post("/encounters/{encounter_id}/vitals")
async def record_vitals(
    encounter_id: str,
    body: VitalSignIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """录入一次生命体征测量。"""
    await assert_encounter_access(db, encounter_id, current_user)
    sign = await inpatient_service.record_vital_sign(
        db,
        encounter_id=encounter_id,
        recorded_at_raw=body.recorded_at,
        fields={
            "temperature": body.temperature,
            "pulse": body.pulse,
            "respiration": body.respiration,
            "bp_systolic": body.bp_systolic,
            "bp_diastolic": body.bp_diastolic,
            "spo2": body.spo2,
            "weight": body.weight,
            "height": body.height,
            "notes": body.notes,
        },
        recorded_by=current_user.real_name or current_user.username,
    )
    return _vital_to_dict(sign)


@router.get("/encounters/{encounter_id}/vitals")
async def get_vitals(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取该接诊的全部体征历史（按时间倒序）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    signs = await inpatient_service.list_vitals(db, encounter_id)
    return {"items": [_vital_to_dict(s) for s in signs]}


@router.get("/encounters/{encounter_id}/vitals/latest")
async def get_latest_vitals(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取最新一次体征记录（用于 AI 生成时注入参考值）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    sign = await inpatient_service.latest_vital(db, encounter_id)
    return _vital_to_dict(sign) if sign else {}


def _vital_to_dict(s: VitalSign) -> dict:
    """将 VitalSign ORM 对象序列化为字典。"""
    return {
        "id": s.id,
        "encounter_id": s.encounter_id,
        "recorded_at": s.recorded_at.isoformat() if s.recorded_at else None,
        "temperature": s.temperature,
        "pulse": s.pulse,
        "respiration": s.respiration,
        "bp_systolic": s.bp_systolic,
        "bp_diastolic": s.bp_diastolic,
        "spo2": s.spo2,
        "weight": s.weight,
        "height": s.height,
        "notes": s.notes,
        "recorded_by": s.recorded_by,
    }


# ── 问题列表 ──────────────────────────────────────────────────────────────────

@router.post("/encounters/{encounter_id}/problems")
async def add_problem(
    encounter_id: str,
    body: ProblemIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """向问题列表新增一条诊断/问题。"""
    await assert_encounter_access(db, encounter_id, current_user)
    item = await inpatient_service.add_problem(
        db,
        encounter_id=encounter_id,
        problem_name=body.problem_name,
        icd_code=body.icd_code,
        onset_date=body.onset_date,
        is_primary=body.is_primary,
        added_by=current_user.real_name or current_user.username,
    )
    return _problem_to_dict(item)


@router.get("/encounters/{encounter_id}/problems")
async def get_problems(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取问题列表（主要诊断优先，活跃问题优先）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    items = await inpatient_service.list_problems(db, encounter_id)
    return {"items": [_problem_to_dict(i) for i in items]}


@router.patch("/encounters/{encounter_id}/problems/{problem_id}")
async def update_problem(
    encounter_id: str,
    problem_id: str,
    body: ProblemPatch,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新问题状态（解决 / 设为主要诊断 / 修改 ICD 码）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    item = await inpatient_service.update_problem(
        db,
        encounter_id=encounter_id,
        problem_id=problem_id,
        status=body.status,
        icd_code=body.icd_code,
        is_primary=body.is_primary,
    )
    return _problem_to_dict(item)


@router.delete("/encounters/{encounter_id}/problems/{problem_id}")
async def delete_problem(
    encounter_id: str,
    problem_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """从问题列表删除一条记录。"""
    await assert_encounter_access(db, encounter_id, current_user)
    await inpatient_service.delete_problem(db, encounter_id, problem_id)
    return {"ok": True}


def _problem_to_dict(p: ProblemItem) -> dict:
    """将 ProblemItem ORM 对象序列化为字典。"""
    return {
        "id": p.id,
        "encounter_id": p.encounter_id,
        "problem_name": p.problem_name,
        "icd_code": p.icd_code,
        "onset_date": p.onset_date,
        "status": p.status,
        "is_primary": p.is_primary,
        "added_by": p.added_by,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


# ── 时效合规检查 ──────────────────────────────────────────────────────────────

# 各类住院文书的书写时限规范（小时）
_COMPLIANCE_RULES = [
    {
        "record_type": "admission_note",
        "label": "入院记录",
        "deadline_hours": 24,
        "required": True,
    },
    {
        "record_type": "first_course_record",
        "label": "首次病程记录",
        "deadline_hours": 8,
        "required": True,
    },
]


@router.get("/encounters/{encounter_id}/compliance")
async def get_compliance(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """检查住院文书时效合规情况。

    返回各类必须文书的完成状态与剩余时间。
    """
    await assert_encounter_access(db, encounter_id, current_user)
    # 获取接诊信息（入院时间）
    enc_result = await db.execute(
        select(Encounter).where(Encounter.id == encounter_id)
    )
    enc = enc_result.scalars().first()
    if not enc:
        raise HTTPException(status_code=404, detail="接诊不存在")

    admission_time = enc.visited_at or datetime.now()
    now = datetime.now()

    # 查询该接诊已有的病历类型
    rec_result = await db.execute(
        select(MedicalRecord.record_type, MedicalRecord.created_at)
        .where(MedicalRecord.encounter_id == encounter_id)
        .order_by(MedicalRecord.created_at.asc())
    )
    existing: dict[str, datetime] = {}
    for row in rec_result.all():
        if row.record_type not in existing:
            existing[row.record_type] = row.created_at

    items = []
    for rule in _COMPLIANCE_RULES:
        deadline = admission_time + timedelta(hours=rule["deadline_hours"])
        done_at = existing.get(rule["record_type"])
        remaining_seconds = (deadline - now).total_seconds()

        if done_at:
            status = "done"
            delay_minutes = (done_at - deadline).total_seconds() / 60
            detail = f"已完成（{'超时' if delay_minutes > 0 else '按时'}）"
        elif remaining_seconds < 0:
            status = "overdue"
            overdue_hours = abs(remaining_seconds) / 3600
            detail = f"已超时 {overdue_hours:.1f} 小时"
        elif remaining_seconds < 3600:
            status = "urgent"
            detail = f"剩余 {remaining_seconds/60:.0f} 分钟"
        else:
            status = "ok"
            detail = f"剩余 {remaining_seconds/3600:.1f} 小时"

        items.append({
            "record_type": rule["record_type"],
            "label": rule["label"],
            "deadline_hours": rule["deadline_hours"],
            "deadline": deadline.isoformat(),
            "status": status,   # done / ok / urgent / overdue
            "detail": detail,
            "done_at": done_at.isoformat() if done_at else None,
        })

    return {
        "encounter_id": encounter_id,
        "admission_time": admission_time.isoformat(),
        "items": items,
    }
