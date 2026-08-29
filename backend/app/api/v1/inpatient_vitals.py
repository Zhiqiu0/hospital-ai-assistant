"""
住院生命体征子路由（/api/v1/encounters/{id}/vitals*）

从 inpatient.py 拆出（Round 5 瘦身）：负责生命体征的录入、历史查询与最新一次查询。
行为与拆分前逐字一致，路由路径/方法/依赖零改动。本模块自建 router，
由 inpatient.py 主 router 拼回。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.authz import assert_encounter_access
from app.database import get_db
from app.models.inpatient import VitalSign
from app.services import inpatient_service

router = APIRouter()


# ── Request 模型 ──────────────────────────────────────────────────────────────

class VitalSignIn(BaseModel):
    """录入生命体征请求体。

    区间口径（2026-08-28 口径对拍修复）：两端统一用**生理极限**而非常见值——
    此前前端 InputNumber min=35 会把真实低体温 34.2 静默钳位成 35（错误数据
    无提示落库），后端又零校验照收 9999。现在：前端下限放宽到生理极限
    （不再钳掉真实异常值），后端同一组极限值兜底拒收离谱输入。
    """
    recorded_at: Optional[str] = None   # ISO8601 字符串，留空则用服务器当前时间
    temperature: Optional[float] = Field(None, ge=25, le=45)
    pulse: Optional[int] = Field(None, ge=0, le=300)
    respiration: Optional[int] = Field(None, ge=0, le=80)
    bp_systolic: Optional[int] = Field(None, ge=20, le=300)
    bp_diastolic: Optional[int] = Field(None, ge=10, le=200)
    spo2: Optional[int] = Field(None, ge=0, le=100)
    weight: Optional[float] = Field(None, ge=0.3, le=400)
    height: Optional[float] = Field(None, ge=20, le=260)
    notes: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def _bp_cross_check(self):
        """收缩压必须大于舒张压（2026-08-29 第七轮审计）：各自区间独立校验
        放行了 30/200 这种两框填反的典型录入错，同臂同次测量物理上不可能，
        拒收让护士/医生当场纠正（与问诊路径 InquiryInputUpdate 同口径）。"""
        if (self.bp_systolic is not None and self.bp_diastolic is not None
                and self.bp_systolic <= self.bp_diastolic):
            raise ValueError(
                f"收缩压 {self.bp_systolic} 不应小于等于舒张压 {self.bp_diastolic}，"
                "请核对两框是否填反")
        return self


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
