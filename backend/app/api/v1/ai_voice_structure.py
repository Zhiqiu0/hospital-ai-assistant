"""
AI 语音结构化子路由（POST /api/v1/ai/voice-structure）

从 ai_voice.py 拆出（Round 5 瘦身）：负责把语音转写文本结构化为问诊字段 +
病历草稿。行为与拆分前逐字一致，路由路径/方法/依赖零改动。
本模块自建 router，由 ai_voice.py 主 router 拼回。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import json
import logging

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.database import get_db
from app.models.voice_record import VoiceRecord
from app.schemas.ai_request import VoiceStructureRequest
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import (
    VOICE_STRUCTURE_PROMPT_INPATIENT,
    VOICE_STRUCTURE_PROMPT_OUTPATIENT,
)
from app.services.ai.record_schemas import sanitize_inline_field
from app.services.ai.task_logger import log_ai_task
from app.services.audit_service import log_action

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/voice-structure")
async def voice_structure(
    req: VoiceStructureRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """将语音转写文本结构化为问诊字段 + 病历草稿（JSON 响应）。"""
    await log_action(
        action="ai_voice_structure",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="voice_record",
        resource_id=req.transcript_id,
        detail=f"visit_type={req.visit_type or 'outpatient'} transcript_len={len(req.transcript or '')}",
    )
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
    # 增量分析基线选择：
    #   优先 existing_record（病历草稿全文，含医生手改，最权威）
    #   退化 existing_inquiry（问诊字段 JSON，仅在病历未生成时使用）
    #   都为空 → 占位"（无）"，prompt 中的"基线非空才严格执行增量规则"自动失效
    record_baseline = (req.existing_record or "").strip()
    if record_baseline:
        existing_baseline = record_baseline
    elif req.existing_inquiry:
        existing_baseline = json.dumps(req.existing_inquiry, ensure_ascii=False)
    else:
        existing_baseline = "（无）"
    # 身份字段防 prompt 注入清洗（2026-06-11）：压平换行 + 截断超长，
    # 防止异常患者姓名等外部输入伪造新的 prompt 段落
    prompt = prompt_template.format(
        patient_name=sanitize_inline_field(req.patient_name, "未提供"),
        patient_gender=sanitize_inline_field(req.patient_gender, "未提供"),
        patient_age=sanitize_inline_field(req.patient_age, "未提供"),
        existing_baseline=existing_baseline,
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
            # 语音结构化结果会被工作台快照引用，失效缓存
            from app.services.encounter_service import invalidate_encounter_snapshot
            if voice_record.encounter_id:
                await invalidate_encounter_snapshot(voice_record.encounter_id)

        return {
            "transcript_id": voice_record.id if voice_record else req.transcript_id,
            "transcript_summary": result.get("transcript_summary", ""),
            "speaker_dialogue": result.get("speaker_dialogue", []),
            "inquiry": result.get("inquiry", {}),
            "draft_record": result.get("draft_record", ""),
        }
    except Exception as exc:
        logger.exception("voice.structure: failed err=%s", exc)
        return {
            "transcript_id": req.transcript_id,
            "transcript_summary": "",
            "speaker_dialogue": [],
            "inquiry": {},
            "draft_record": "",
        }
