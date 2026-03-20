from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from typing import Optional
from app.database import get_db
from app.core.security import require_admin
from app.models.voice_record import VoiceRecord
from app.models.user import User

router = APIRouter()


@router.get("")
async def list_voice_records(
    keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    query = (
        select(VoiceRecord)
        .options(selectinload(VoiceRecord.doctor))
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
