"""
接诊生命周期子路由（/api/v1/encounters/*）

从 encounters.py 拆出（Round 5 瘦身）：负责接诊记录的查询与状态流转
（my / discharge / cancel / get / workspace）。行为与拆分前逐字一致，
路由路径/方法/依赖零改动。本模块自建 router，由 encounters.py 主 router 拼回。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.authz import assert_encounter_access
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.encounter import (
    EncounterCancelRequest,
    EncounterResponse,
)
from app.services.encounter_service import EncounterService
from app.models.encounter import Encounter as EncounterModel

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/my")
async def get_my_encounters(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取当前医生进行中的接诊列表。"""
    service = EncounterService(db)
    return await service.get_my_encounters(current_user.id)


@router.post("/{encounter_id}/discharge")
async def discharge_encounter(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """办理出院：把住院接诊状态置为 completed，从病区列表移除。

    业务规则：
      - 仅住院类型（visit_type='inpatient'）才需要走此接口
      - 仅当前主治医生（doctor_id 匹配）可办理
      - 重复调用幂等：已 completed 的接诊不报错，直接返回
      - 关闭后失效 my_encounters 缓存 + 接诊快照缓存
    """
    result = await db.execute(
        select(EncounterModel).where(EncounterModel.id == encounter_id)
    )
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=404, detail="接诊不存在")
    if encounter.doctor_id != current_user.id:
        raise HTTPException(status_code=403, detail="只有主治医生可办理出院")
    if encounter.visit_type != "inpatient":
        raise HTTPException(status_code=400, detail="仅住院接诊可办理出院")

    if encounter.status == "completed":
        return {"ok": True, "already_discharged": True, "encounter_id": encounter_id}

    encounter.status = "completed"
    await db.commit()

    # 失效缓存：接诊列表 + 快照 + 该患者基本信息（has_active_inpatient 变了 → 在院/已出院 标签会变）
    from app.services.encounter_service import (
        invalidate_encounter_snapshot,
        invalidate_my_encounters,
    )
    from app.services.patient_service import _invalidate_patient_cache
    await invalidate_encounter_snapshot(encounter_id)
    await invalidate_my_encounters(current_user.id)
    await _invalidate_patient_cache(encounter.patient_id)

    return {"ok": True, "already_discharged": False, "encounter_id": encounter_id}


@router.post("/{encounter_id}/cancel")
async def cancel_encounter(
    encounter_id: str,
    data: EncounterCancelRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """取消接诊（软取消，所有数据保留供回溯）。

    业务详情见 EncounterService.cancel 实现注释。
    """
    service = EncounterService(db)
    result = await service.cancel(
        encounter_id=encounter_id,
        operator_doctor_id=current_user.id,
        cancel_reason=data.cancel_reason,
    )
    logger.info(
        "encounter.cancel: encounter_id=%s by=%s reason=%r",
        encounter_id, current_user.id, data.cancel_reason,
    )
    return result


@router.get("/{encounter_id}", response_model=EncounterResponse)
async def get_encounter(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """按 ID 查询单条接诊记录。"""
    # 归属校验：非管理员只能读自己接诊，防止越权拿他人接诊详情（IDOR）
    await assert_encounter_access(db, encounter_id, current_user)
    service = EncounterService(db)
    return await service.get_by_id(encounter_id)


@router.get("/{encounter_id}/workspace")
async def get_encounter_workspace(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """恢复工作台：返回患者、问诊、最近病历及语音记录的完整快照。"""
    service = EncounterService(db)
    return await service.get_workspace_snapshot(encounter_id, current_user.id)
