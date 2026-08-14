"""
病程记录路由（/api/v1/encounters/{encounter_id}/progress-notes）

端点列表：
  GET    /                  获取某接诊的全部病程记录（按书写时间排序）
  POST   /                  新建病程记录
  PATCH  /{note_id}         更新内容/状态（已签发的整条冻结）
  DELETE /{note_id}         删除（仅 draft 状态允许）

业务层在 app.services.progress_notes_service；本文件只做请求/响应组装。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import get_current_user
from app.core.authz import assert_can_write_record, assert_encounter_access
from app.models.inpatient import ProgressNote
from app.services import progress_notes_service

router = APIRouter()
logger = logging.getLogger(__name__)


class ProgressNoteIn(BaseModel):
    note_type: str = "daily_course"
    title: Optional[str] = None
    content: str = ""
    recorded_at: Optional[str] = None  # ISO 字符串，允许手动填写过去时间


class ProgressNotePatch(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    recorded_at: Optional[str] = None


def _note_to_dict(n: ProgressNote) -> dict:
    return {
        "id": n.id,
        "encounter_id": n.encounter_id,
        "note_type": n.note_type,
        "title": n.title,
        "content": n.content,
        "recorded_at": n.recorded_at.isoformat() if n.recorded_at else None,
        "recorded_by": n.recorded_by,
        "status": n.status,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "updated_at": n.updated_at.isoformat() if n.updated_at else None,
    }


@router.get("/encounters/{encounter_id}/progress-notes")
async def list_progress_notes(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取该接诊的全部病程记录。"""
    await assert_encounter_access(db, encounter_id, current_user)
    notes = await progress_notes_service.list_notes(db, encounter_id)
    return {"items": [_note_to_dict(n) for n in notes]}


@router.post("/encounters/{encounter_id}/progress-notes", status_code=201)
async def create_progress_note(
    encounter_id: str,
    data: ProgressNoteIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """新建病程记录。"""
    await assert_encounter_access(db, encounter_id, current_user)
    # 角色守卫（2026-08-14 第八轮审计）：病程记录是住院病历的**法定组成部分**，
    # recorded_by 直接取 current_user.real_name，且 PATCH status='submitted'
    # 能一路走到签发冻结点。而这三个写端点原先只挂了归属校验、没有角色校验——
    # 护士/影像科在自己名下的接诊上可以写出并签发一份署自己名字的病程记录，
    # 直接违反医院「病历署名必须是接诊医生本人」的硬要求。
    # 同为病历文书写入，medical_records.py 那边四个端点里三个都挂了这道守卫。
    assert_can_write_record(current_user)
    note = await progress_notes_service.create_note(
        db,
        encounter_id=encounter_id,
        note_type=data.note_type,
        title=data.title,
        content=data.content,
        recorded_at_raw=data.recorded_at,
        recorded_by=getattr(current_user, "real_name", None) or current_user.username,
    )
    # 业务里程碑：病程记录创建（不打 content，仅 ID/类型用于复盘谁建的）
    logger.info(
        "progress_note.create: ok note_id=%s encounter_id=%s type=%s",
        note.id, encounter_id, data.note_type,
    )
    return _note_to_dict(note)


@router.patch("/encounters/{encounter_id}/progress-notes/{note_id}")
async def update_progress_note(
    encounter_id: str,
    note_id: str,
    data: ProgressNotePatch,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新病程记录（已签发整条冻结，status 白名单 draft/submitted）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    assert_can_write_record(current_user)  # 角色守卫，理由见本文件 create 端点
    note = await progress_notes_service.update_note(
        db,
        encounter_id=encounter_id,
        note_id=note_id,
        title=data.title,
        content=data.content,
        status=data.status,
        recorded_at_raw=data.recorded_at,
        # 谁写的正文就署谁（审计：交接后署名仍是前一位医生）
        editor_name=getattr(current_user, "real_name", None) or current_user.username,
    )
    # 业务里程碑：病程记录签发（status=submitted 是冻结点）
    if data.status == "submitted":
        logger.info(
            "progress_note.sign: submitted note_id=%s encounter_id=%s type=%s",
            note_id, encounter_id, note.note_type,
        )
    return _note_to_dict(note)


@router.delete("/encounters/{encounter_id}/progress-notes/{note_id}", status_code=204)
async def delete_progress_note(
    encounter_id: str,
    note_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除病程记录（仅 draft 状态）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    assert_can_write_record(current_user)  # 角色守卫，理由见本文件 create 端点
    await progress_notes_service.delete_note(db, encounter_id, note_id)
