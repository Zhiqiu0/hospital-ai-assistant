"""
管理后台语音记录管理接口（/api/v1/admin/voice-records/*）

端点列表：
  GET /  分页查询所有语音记录（支持状态过滤和转写关键词搜索）

仅管理员可访问（require_admin）。
语音记录由医生在接诊工作台录制，经 ASR 转写后保存。
此接口供管理员查看整体录音使用情况，不提供音频文件播放（音频播放在 ai_voice.py）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import require_admin
from app.database import get_db
from app.models.voice_record import VoiceRecord

router = APIRouter()


@router.get("")
async def list_voice_records(
    keyword: Optional[str] = Query(None, description="在转写文本中模糊搜索"),
    status: Optional[str] = Query(None, description="按状态过滤（uploaded / structured 等）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """分页查询所有语音记录，预加载医生信息（避免 N+1）。"""
    query = (
        select(VoiceRecord)
        .options(selectinload(VoiceRecord.doctor))  # 预加载医生信息，显示 doctor_name
        .order_by(desc(VoiceRecord.created_at))
    )
    if status:
        query = query.where(VoiceRecord.status == status)
    if keyword:
        query = query.where(VoiceRecord.raw_transcript.ilike(f"%{keyword}%"))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    records = result.scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "status": r.status,
                "visit_type": r.visit_type,
                "encounter_id": r.encounter_id,
                "doctor_name": r.doctor.real_name if r.doctor else None,
                "has_audio": bool(r.audio_file_path),
                "transcript_preview": (r.raw_transcript or "")[:100],
                "transcript_summary": r.transcript_summary or "",
            }
            for r in records
        ],
    }
