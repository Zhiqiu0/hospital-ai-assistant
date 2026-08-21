# -*- coding: utf-8 -*-
"""诊断条目端点（api/v1/encounters_diagnoses.py，2026-08-21 阶段1a）

  GET /{encounter_id}/diagnoses  拉取接诊全部诊断条目
  PUT /{encounter_id}/diagnoses  整组替换写入（含校验 + 文本投影双写）

由 encounters.py 主 router include（与 encounters_inquiry 同模式）。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import assert_can_write_record, assert_encounter_access
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.diagnosis import DiagnosisItemOut, DiagnosisListUpdate
from app.services.diagnosis_service import DiagnosisService

router = APIRouter()


@router.get("/{encounter_id}/diagnoses", response_model=list[DiagnosisItemOut])
async def list_diagnoses(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """拉取接诊的全部诊断条目（主诊断优先）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    return await DiagnosisService(db).list_by_encounter(encounter_id)


@router.put("/{encounter_id}/diagnoses", response_model=list[DiagnosisItemOut])
async def replace_diagnoses(
    encounter_id: str,
    data: DiagnosisListUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """整组替换诊断条目。

    角色守卫与病历书写同口径（诊断是病历/病案首页的法定内容，护士等
    无病历书写权的角色不得改动）；归属校验防越权写他人接诊。
    """
    assert_can_write_record(current_user)
    await assert_encounter_access(db, encounter_id, current_user)
    return await DiagnosisService(db).replace_all(
        encounter_id,
        data.items,
        added_by=getattr(current_user, "real_name", None) or getattr(current_user, "username", None),
    )
