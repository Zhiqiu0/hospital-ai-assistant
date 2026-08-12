"""
AI 语音记录子路由（/api/v1/ai/voice-records/*）

从 ai_voice.py 拆出（Round 5 瘦身）：负责语音文件的上传（含 ASR 转写）、
播放令牌颁发、播放与删除。行为与拆分前逐字一致，路由路径/方法/依赖零改动。
本模块自建 router，由 ai_voice.py 主 router 拼回。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
from pathlib import Path
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings
from app.core.security import get_current_user
from app.core.upload_limits import MAX_AUDIO_BYTES, read_upload_capped
from app.database import get_db
from app.models.base import generate_uuid
from app.models.voice_record import VoiceRecord
from app.api.v1._ai_voice_helpers import _asr_qwen_audio

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/voice-records/upload")
async def upload_voice_record(
    file: UploadFile = File(...),
    encounter_id: Optional[str] = Form(None),
    visit_type: Optional[str] = Form("outpatient"),
    transcript: Optional[str] = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """上传语音文件，可选 ASR 转写（优先使用浏览器端转写，无则调 Qwen-Audio 兜底）。"""
    uploads_root = Path(__file__).resolve().parents[3] / "uploads"
    rel_dir = Path("voice_records") / (encounter_id or "no_encounter")
    (uploads_root / rel_dir).mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "recording.webm").suffix or ".webm"
    file_name = f"{generate_uuid()}{suffix}"
    rel_path = rel_dir / file_name
    # 分块读 + 超 50MB 即 413，避免超大录音吃满内存
    audio_bytes = await read_upload_capped(file, MAX_AUDIO_BYTES)
    (uploads_root / rel_path).write_bytes(audio_bytes)

    # 浏览器端转写优先；无则 Qwen-Audio 兜底
    asr_transcript = (transcript or "").strip()
    if settings.aliyun_api_key and not asr_transcript:
        asr_transcript = await _asr_qwen_audio(audio_bytes, file.filename or "recording.webm")

    record = VoiceRecord(
        encounter_id=encounter_id,
        doctor_id=current_user.id,
        visit_type=visit_type or "outpatient",
        raw_transcript=asr_transcript,
        audio_file_path=str(rel_path),
        mime_type=file.content_type or "application/octet-stream",
        status="uploaded",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    # 工作台快照含 latest_voice_record，新上传需失效缓存
    from app.services.encounter_service import invalidate_encounter_snapshot
    await invalidate_encounter_snapshot(encounter_id)
    return {
        "voice_record_id": record.id,
        "status": record.status,
        "has_audio": True,
        "transcript": asr_transcript,
    }


@router.get("/voice-records/{voice_record_id}/audio-token")
async def get_audio_token(
    voice_record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """为指定语音记录颁发短期音频令牌（有效期 5 分钟）。

    解决方案说明（Bug B 修复）：
      HTML <audio> 元素无法设置自定义请求头，音频 URL 必须携带凭证。
      原做法把完整 JWT 放 query 参数，会被写入服务器访问日志，存在安全风险。
      改进后：前端先调用此端点获取短期令牌，再将短期令牌放入音频 URL，
      即使 URL 被日志记录，5 分钟后自动失效且只能访问该特定音频文件。

    Returns:
        { "audio_token": "<短期JWT>" }
    """
    # 验证该语音记录存在且属于当前用户（管理员可访问所有）
    query = select(VoiceRecord).where(VoiceRecord.id == voice_record_id)
    if current_user.role not in ("admin", "super_admin"):
        query = query.where(VoiceRecord.doctor_id == current_user.id)
    result = await db.execute(query)
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="语音记录不存在")

    from app.core.security import create_audio_token
    audio_token = create_audio_token(
        user_id=current_user.id,
        voice_record_id=voice_record_id,
    )
    return {"audio_token": audio_token}


@router.get("/voice-records/{voice_record_id}/audio")
async def get_voice_audio(
    voice_record_id: str,
    token: str = Query(..., description="短期音频令牌（由 /audio-token 端点颁发，有效期 5 分钟）"),
    db: AsyncSession = Depends(get_db),
):
    """播放语音文件。

    鉴权方式：
      接受由 GET /voice-records/{id}/audio-token 颁发的短期音频令牌。
      短期令牌（aud="audio"）与普通会话令牌（aud 不含 "audio"）严格区分，
      即使普通会话令牌泄露也无法直接访问音频端点。

    为什么用 query param 而不是 Authorization header：
      HTML <audio> 元素不支持自定义请求头，必须将凭证放在 URL 中。
      使用短期令牌（5 分钟过期、仅限特定资源）将暴露窗口降到最低。
    """
    from app.core.security import verify_audio_token

    # 验证短期音频令牌，获取用户 ID 和资源 ID
    user_id, token_record_id = verify_audio_token(token)

    # 令牌中的资源 ID 必须与 URL 路径参数一致，防止令牌被用于访问其他文件
    if token_record_id != voice_record_id:
        raise HTTPException(status_code=403, detail="令牌与请求资源不匹配")

    result = await db.execute(
        select(VoiceRecord).where(VoiceRecord.id == voice_record_id)
    )
    record = result.scalar_one_or_none()
    if not record or not record.audio_file_path:
        raise HTTPException(status_code=404, detail="音频文件不存在")

    uploads_root = Path(__file__).resolve().parents[3] / "uploads"
    audio_path = uploads_root / record.audio_file_path
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="音频文件已被清理")

    return FileResponse(audio_path, media_type=record.mime_type or "audio/webm", filename=audio_path.name)


@router.delete("/voice-records/{voice_record_id}")
async def delete_voice_record(
    voice_record_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除语音记录及磁盘音频文件（仅本人可删）。"""
    result = await db.execute(
        select(VoiceRecord).where(
            VoiceRecord.id == voice_record_id,
            VoiceRecord.doctor_id == current_user.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="语音记录不存在")

    if record.audio_file_path:
        audio_path = Path(__file__).resolve().parents[3] / "uploads" / record.audio_file_path
        if audio_path.exists():
            audio_path.unlink()

    eid = record.encounter_id
    await db.delete(record)
    await db.commit()
    # 删除语音也要失效快照（latest_voice_record 字段会变）
    if eid:
        from app.services.encounter_service import invalidate_encounter_snapshot
        await invalidate_encounter_snapshot(eid)
    return {"success": True}
