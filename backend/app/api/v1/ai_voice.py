"""
AI 语音相关路由（/api/v1/ai/voice-records/*, /api/v1/ai/voice-structure）

端点列表：
  POST   /voice-records/upload              上传语音文件（含 ASR 转写）
  GET    /voice-records/{id}/audio          播放语音文件（query-token 鉴权）
  DELETE /voice-records/{id}               删除语音记录及磁盘文件
  POST   /voice-structure                   语音文本结构化为问诊字段
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import base64
import json
import logging
from pathlib import Path
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings
from app.core.security import get_current_user
from app.database import get_db
from app.models.base import generate_uuid
from app.models.voice_record import VoiceRecord
from app.schemas.ai_request import VoiceStructureRequest
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import (
    VOICE_STRUCTURE_PROMPT_INPATIENT,
    VOICE_STRUCTURE_PROMPT_OUTPATIENT,
)
from app.services.ai.task_logger import log_ai_task

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 私有辅助 ──────────────────────────────────────────────────────────────────

async def _asr_qwen_audio(audio_bytes: bytes, filename: str) -> str:
    """调用阿里云 Qwen-Audio-Turbo 对音频执行 ASR 转写。

    Args:
        audio_bytes: 原始音频二进制内容。
        filename: 原始文件名，用于推断 MIME 类型。

    Returns:
        转写结果字符串；API 调用失败或异常时返回空字符串。
    """
    try:
        audio_b64 = base64.b64encode(audio_bytes).decode()
        suffix = Path(filename).suffix.lstrip(".") or "webm"
        mime_map = {"m4a": "mp4", "mp3": "mpeg"}
        audio_mime = f"audio/{mime_map.get(suffix, suffix)}"

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
                headers={
                    "Authorization": f"Bearer {settings.aliyun_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "qwen-audio-turbo",
                    "input": {
                        "messages": [{
                            "role": "user",
                            "content": [
                                {"audio": f"data:{audio_mime};base64,{audio_b64}"},
                                {"text": "请转录这段中文医患录音，只输出转录文字，不添加任何解释或标注。"},
                            ],
                        }]
                    },
                },
            )
        if resp.status_code != 200:
            logger.warning("Qwen-Audio 转写失败: HTTP %s — %s", resp.status_code, resp.text[:200])
            return ""
        data = resp.json()
        content = (
            data.get("output", {})
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", [])
        )
        if isinstance(content, list):
            return " ".join(
                item["text"] for item in content if isinstance(item, dict) and "text" in item
            ).strip()
        if isinstance(content, str):
            return content.strip()
    except Exception as exc:
        logger.warning("Qwen-Audio 转写异常: %s", exc)
    return ""


# ── 路由处理器 ────────────────────────────────────────────────────────────────

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
    audio_bytes = await file.read()
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

    await db.delete(record)
    await db.commit()
    return {"success": True}


@router.post("/voice-structure")
async def voice_structure(
    req: VoiceStructureRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """将语音转写文本结构化为问诊字段 + 病历草稿（JSON 响应）。"""
    transcript = (req.transcript or "").strip()
    if not transcript:
        return {"transcript_summary": "", "inquiry": {}, "draft_record": ""}

    voice_record = None
    if req.transcript_id:
        voice_result = await db.execute(
            select(VoiceRecord).where(
                VoiceRecord.id == req.transcript_id,
                VoiceRecord.doctor_id == current_user.id,
            )
        )
        voice_record = voice_result.scalar_one_or_none()
        if not voice_record:
            raise HTTPException(status_code=404, detail="语音记录不存在")

    visit_type = req.visit_type or "outpatient"
    prompt_template = (
        VOICE_STRUCTURE_PROMPT_INPATIENT if visit_type == "inpatient"
        else VOICE_STRUCTURE_PROMPT_OUTPATIENT
    )
    model_options = await get_model_options(db, "generate")
    prompt = prompt_template.format(
        patient_name=req.patient_name or "未提供",
        patient_gender=req.patient_gender or "未提供",
        patient_age=req.patient_age or "未提供",
        existing_inquiry=json.dumps(req.existing_inquiry or {}, ensure_ascii=False),
        transcript=transcript,
    )

    messages = [
        {"role": "system", "content": "你是临床病历整理助手，只输出合法 JSON，禁止输出解释说明。"},
        {"role": "user", "content": prompt},
    ]
    try:
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "generate",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
        )

        if voice_record:
            voice_record.raw_transcript = transcript
            voice_record.transcript_summary = result.get("transcript_summary", "")
            voice_record.speaker_dialogue = json.dumps(result.get("speaker_dialogue", []), ensure_ascii=False)
            voice_record.structured_inquiry = json.dumps(result.get("inquiry", {}), ensure_ascii=False)
            voice_record.draft_record = result.get("draft_record", "")
            voice_record.status = "structured"
            await db.commit()

        return {
            "transcript_id": voice_record.id if voice_record else req.transcript_id,
            "transcript_summary": result.get("transcript_summary", ""),
            "speaker_dialogue": result.get("speaker_dialogue", []),
            "inquiry": result.get("inquiry", {}),
            "draft_record": result.get("draft_record", ""),
        }
    except Exception as exc:
        logger.error("voice_structure failed: %s", exc, exc_info=True)
        return {
            "transcript_id": req.transcript_id,
            "transcript_summary": "",
            "speaker_dialogue": [],
            "inquiry": {},
            "draft_record": "",
        }
