"""
AI 诊疗建议路由（/api/v1/ai/inquiry-suggestions 等）

端点列表：
  POST   /inquiry-suggestions    生成临床追问建议（JSON）
  POST   /exam-suggestions       生成辅助检查建议（JSON）
  POST   /diagnosis-suggestion   生成初步诊断建议（JSON）
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.ai_request import (
    DiagnosisSuggestionRequest,
    ExamSuggestionsRequest,
    InquirySuggestionsRequest,
)
from app.services.ai.ai_utils import get_active_prompt, safe_format
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import (
    DIAGNOSIS_SUGGESTION_PROMPT,
    EXAM_SUGGESTIONS_PROMPT,
    INQUIRY_SUGGESTIONS_PROMPT,
)
from app.services.ai.task_logger import log_ai_task

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/inquiry-suggestions")
async def inquiry_suggestions(
    req: InquirySuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """生成临床追问建议（JSON 响应）。"""
    from app.core.request_context import bind_encounter_context
    bind_encounter_context(encounter_id=req.encounter_id)

    db_prompt = await get_active_prompt(db, "inquiry")
    template = db_prompt or INQUIRY_SUGGESTIONS_PROMPT
    prompt = safe_format(
        template,
        chief_complaint=req.chief_complaint or "未填写",
        history=req.history_present_illness or "未填写",
        initial_impression=req.initial_impression or "暂未填写",
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是临床问诊专家，只输出JSON对象，包含known_info、condition_type、suggestions三个字段。"
                "known_info：列出已知信息要点的字符串数组。"
                "condition_type：病情类型字符串。"
                "suggestions：追问问题数组，每项含text、priority、is_red_flag、category、options，"
                "其中text不得重复known_info中已有的内容，options为2-4个专业具体选项。"
                "对于擦伤/外伤等已明确诊断的病例，禁止生成询问症状类型、持续时间等基础问题。"
            ),
        },
        {"role": "user", "content": prompt},
    ]
    try:
        model_options = await get_model_options(db, "inquiry")
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "inquiry",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
            output_result=result,  # snapshot 恢复时能取回，logout 重登不丢
        )
        return result
    except Exception as exc:
        logger.exception("ai.inquiry_suggestions: failed err=%s", exc)
        return {"suggestions": []}


@router.post("/exam-suggestions")
async def exam_suggestions(
    req: ExamSuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """生成辅助检查建议（JSON 响应）。"""
    from app.core.request_context import bind_encounter_context
    bind_encounter_context(encounter_id=req.encounter_id)

    db_prompt = await get_active_prompt(db, "exam")
    template = db_prompt or EXAM_SUGGESTIONS_PROMPT
    prompt = safe_format(
        template,
        chief_complaint=req.chief_complaint or "未填写",
        history_present_illness=req.history_present_illness or "未填写",
        initial_impression=req.initial_impression or "未填写",
        department=req.department or "未知",
    )
    try:
        model_options = await get_model_options(db, "exam")
        result = await llm_client.chat_json_stream(
            [{"role": "user", "content": prompt}],
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "exam",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
            output_result=result,  # snapshot 恢复时能取回
        )
        return result
    except Exception as exc:
        logger.exception("ai.exam_suggestions: failed err=%s", exc)
        return {"suggestions": []}


@router.post("/diagnosis-suggestion")
async def diagnosis_suggestion(
    req: DiagnosisSuggestionRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """根据问诊及追问结果生成初步诊断建议（JSON 响应）。"""
    from app.core.request_context import bind_encounter_context
    bind_encounter_context(encounter_id=req.encounter_id)

    answers_text = "\n".join(
        f"- {item.get('question', '')}: {item.get('answer', '')}"
        for item in (req.inquiry_answers or [])
    ) or "（暂无追问记录）"

    prompt = safe_format(
        DIAGNOSIS_SUGGESTION_PROMPT,
        chief_complaint=req.chief_complaint or "未填写",
        history=req.history_present_illness or "未填写",
        initial_impression=req.initial_impression or "未填写",
        inquiry_answers=answers_text,
    )
    messages = [
        {
            "role": "system",
            "content": "你是临床诊断助手，只输出JSON，diagnoses数组中每项必须包含name、confidence、reasoning、next_steps字段。",
        },
        {"role": "user", "content": prompt},
    ]
    try:
        model_options = await get_model_options(db, "inquiry")
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "diagnosis",  # 之前误写成 'inquiry' 跟追问混了，task_type 改正
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
            output_result=result,
        )
        return result
    except Exception as exc:
        logger.exception("ai.diagnosis_suggestion: failed err=%s", exc)
        return {"diagnoses": []}
