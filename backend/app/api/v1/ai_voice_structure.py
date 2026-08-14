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
from app.services.ai.output_guards import (
    strip_unsubstantiated_vital_values,
    strip_unsubstantiated_vitals,
)
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

    # 连接池护栏：上面的读已取完（voice_record + model_options），下面是最长 270s 的
    # LLM 调用。这里先 commit 结束只读事务、把 asyncpg 连接还回池——否则整个 LLM 期间
    # 都占着一条连接，十几个医生并发跑就把 30 连接的池占满、其余请求排队超时。
    # expire_on_commit=False，voice_record 对象 commit 后仍可读写；LLM 完再写回时
    # 会短暂重新借一条连接，不影响。
    await db.commit()

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
            model_name=model_options.get("model_name"),  # 真实模型，非全局默认（审计 #7）
        )

        # ── 数值真实性红线守卫（2026-08-14 第八轮审计）─────────────────────
        #
        # prompts_voice 规定「生命体征只填 vital_signs 结构体，严禁出现在
        # physical_exam 文字里」——这条为字段归位而写的规则，恰好把体征数值
        # 从**受 output_guards 保护的文本**挪进了**守卫够不到的结构体**，
        # 于是这条路径上只剩 prompt 里那句「未提及留空」的软约束。
        # 而 output_guards 的模块注释早就写明：软约束不够，实测 LLM 仍会编
        # 「默认正常」的体征数值。语音又是医生最主要的输入路径，编出来的体温
        # 直接落进工作台输入框，医生签发后连同病历回写 HIS。
        # 这里做确定性后校验：数值必须在医生口述原文里字面出现才保留。
        inquiry_result = result.get("inquiry") or {}
        if isinstance(inquiry_result, dict) and inquiry_result.get("vital_signs"):
            kept, dropped = strip_unsubstantiated_vital_values(
                inquiry_result["vital_signs"], transcript
            )
            inquiry_result["vital_signs"] = kept
            if dropped:
                logger.warning(
                    "voice.structure: 剔除无出处的生命体征数值 %s（口述原文里查无此数）"
                    " transcript_id=%s", ",".join(dropped), req.transcript_id,
                )
            result["inquiry"] = inquiry_result

        # draft_record 是含【体格检查】章节的**病历草稿全文**，直接显示进编辑区。
        # 它是文本，走文本版守卫（同一条红线的另一个出口，同样原先没挂）。
        draft = result.get("draft_record")
        if isinstance(draft, str) and draft:
            cleaned_draft = strip_unsubstantiated_vitals(draft, transcript)
            if cleaned_draft != draft:
                logger.warning(
                    "voice.structure: 病历草稿里剔除了无出处的体征数值 transcript_id=%s",
                    req.transcript_id,
                )
                result["draft_record"] = cleaned_draft

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
