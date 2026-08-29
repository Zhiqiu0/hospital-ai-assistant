"""
接诊问诊子路由（/api/v1/encounters/{id}/inquiry、previous-record）

从 encounters.py 拆出（Round 5 瘦身）：负责问诊输入保存、上次病历同步。
本模块自建 router，由 encounters.py 主 router 拼回。

2026-08-29 第六轮审计清理：本模块原有的 inquiry-suggestions（SSE 流）与
exam-suggestions 两个 AI 建议端点前端从未消费（前端走 /ai/* 的 JSON 版），
连同 InquiryService/ExamService 与 schemas/ai_suggestion.py 一并删除。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.authz import assert_encounter_access
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.encounter import InquiryInputUpdate
from app.services.encounter_service import EncounterService

router = APIRouter()


@router.put("/{encounter_id}/inquiry")
async def save_inquiry_input(
    encounter_id: str,
    data: InquiryInputUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """保存 / 更新问诊输入字段。"""
    # 归属校验：只能写自己接诊的问诊，防止越权覆写他人接诊数据
    await assert_encounter_access(db, encounter_id, current_user)
    service = EncounterService(db)
    return await service.save_inquiry(encounter_id, data)


@router.get("/{encounter_id}/previous-record")
async def get_previous_record(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """一键同步上次病历：返回该患者上次接诊的病历文字字段（体征不带回，需本次重测）。"""
    # 归属校验：只能对自己的接诊拉上次病历，防止越权拿他人患者的历史问诊全文
    await assert_encounter_access(db, encounter_id, current_user)
    service = EncounterService(db)
    return await service.get_previous_record(encounter_id)
