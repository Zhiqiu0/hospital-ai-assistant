"""
住院生命体征子路由（/api/v1/encounters/{id}/vitals*）

从 inpatient.py 拆出（Round 5 瘦身）：负责生命体征的录入、历史查询与最新一次查询。
行为与拆分前逐字一致，路由路径/方法/依赖零改动。本模块自建 router，
由 inpatient.py 主 router 拼回。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.authz import assert_encounter_access
from app.database import get_db
from app.models.inpatient import VitalSign
from app.services import inpatient_service

router = APIRouter()


# ── Request 模型 ──────────────────────────────────────────────────────────────

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
