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
from app.services.ai.ai_utils import guarded_messages, safe_format
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


def _sanitize_llm_result(
    result,
    list_key: str,
    item_keys: dict,
    extra_keys: dict | None = None,
) -> dict:
    """LLM JSON 键白名单收口（2026-08-29 第六轮提示注入审计）。

    此前三个建议端点把 json.loads 的结果零校验原样返回前端，并经
    log_ai_task 的 output_result 落 JSONB、重登快照时再回放——LLM 被注入
    或抽风时任意键/超大嵌套结构会长期驻留并污染前端 store。这里按前端
    实际消费的契约键收口：白名单外的键丢弃、类型不符的值丢弃、列表与
    字符串截断兜量。

    Args:
        item_keys: 列表项的 {键: 期望类型}（str/bool/list）
        extra_keys: 顶层附加键的 {键: 期望类型}
    """
    if not isinstance(result, dict):
        return {list_key: []}
    out: dict = {}
    items = result.get(list_key)
    clean_items = []
    if isinstance(items, list):
        for it in items[:20]:
            if not isinstance(it, dict):
                continue
            ci = {}
            for k, t in item_keys.items():
                v = it.get(k)
                if t is str and isinstance(v, str):
                    ci[k] = v[:2000]
                elif t is bool and isinstance(v, bool):
                    ci[k] = v
                elif t is list and isinstance(v, list):
                    ci[k] = [str(x)[:200] for x in v[:10]]
            clean_items.append(ci)
    out[list_key] = clean_items
    for k, t in (extra_keys or {}).items():
        v = result.get(k)
        if t is str and isinstance(v, str):
            out[k] = v[:500]
        elif t is list and isinstance(v, list):
            out[k] = [str(x)[:500] for x in v[:20]]
    return out


@router.post("/inquiry-suggestions")
async def inquiry_suggestions(
    req: InquirySuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """生成临床追问建议（JSON 响应）。"""
    from app.core.request_context import bind_encounter_context
    bind_encounter_context(encounter_id=req.encounter_id)

    # 提示词只用代码内置版本（DB 自定义模板已于 2026-08-18 撤掉）
    prompt = safe_format(
        INQUIRY_SUGGESTIONS_PROMPT,
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
        model_options = get_model_options("inquiry")
        # 连接池护栏：进入最长 270s 的 LLM 调用前先 commit 结束本请求此前的只读事务
        # （若有）、把 asyncpg 连接还回池，避免长 await 期间白占一条池连接。
        # log_ai_task 用独立会话，不受影响。
        await db.commit()
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        # 契约键收口（见 _sanitize_llm_result）：先收口再落库/返回，
        # 快照回放的也是干净结构
        result = _sanitize_llm_result(
            result, "suggestions",
            {"text": str, "priority": str, "category": str,
             "options": list, "is_red_flag": bool},
            {"known_info": list, "condition_type": str},
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "inquiry",
            token_input=usage.prompt_tokens if usage else None,
            token_output=usage.completion_tokens if usage else None,
            output_result=result,  # snapshot 恢复时能取回，logout 重登不丢
            # 记真实用到的模型，而不是全局默认（审计 #7）
            model_name=model_options.get("model_name"),
        )
        return result
    except Exception as exc:
        logger.exception("ai.inquiry_suggestions: failed err=%s", exc)
        # degraded=True 让前端区分"AI 故障"和"真的没有建议"（2026-06-11）
        return {"suggestions": [], "degraded": True}


@router.post("/exam-suggestions")
async def exam_suggestions(
    req: ExamSuggestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """生成辅助检查建议（JSON 响应）。"""
    from app.core.request_context import bind_encounter_context
    bind_encounter_context(encounter_id=req.encounter_id)

    prompt = safe_format(
        EXAM_SUGGESTIONS_PROMPT,
        chief_complaint=req.chief_complaint or "未填写",
        history_present_illness=req.history_present_illness or "未填写",
        initial_impression=req.initial_impression or "未填写",
        department=req.department or "未知",
    )
    try:
        model_options = get_model_options("exam")
        # 连接池护栏：进入最长 270s 的 LLM 调用前先 commit 结束本请求此前的只读事务
        # （若有）、把连接还回池，避免长 await 期间白占一条池连接。
        # log_ai_task 用独立会话，不受影响。
        await db.commit()
        result = await llm_client.chat_json_stream(
            # 注入守卫（2026-08-29 第六轮审计）：三端点中唯独本端点没有 system
            # 消息，主诉/现病史直接混在指令里
            guarded_messages(prompt),
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        # 契约键收口（见 _sanitize_llm_result）
        result = _sanitize_llm_result(
            result, "suggestions",
            {"exam_name": str, "category": str, "reason": str},
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "exam",
            token_input=usage.prompt_tokens if usage else None,
            token_output=usage.completion_tokens if usage else None,
            output_result=result,  # snapshot 恢复时能取回
            model_name=model_options.get("model_name"),  # 审计 #7
        )
        return result
    except Exception as exc:
        logger.exception("ai.exam_suggestions: failed err=%s", exc)
        # degraded=True 让前端区分"AI 故障"和"真的没有建议"（2026-06-11）
        return {"suggestions": [], "degraded": True}


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
        model_options = get_model_options("inquiry")
        # 连接池护栏：进入最长 270s 的 LLM 调用前先 commit 结束本请求此前的只读事务（若有）、
        # 只读事务、把连接还回池，避免长 await 期间白占一条池连接。
        await db.commit()
        result = await llm_client.chat_json_stream(
            messages,
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        # 契约键收口（见 _sanitize_llm_result）
        result = _sanitize_llm_result(
            result, "diagnoses",
            {"name": str, "confidence": str, "reasoning": str,
             "next_steps": str},
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "diagnosis",  # 之前误写成 'inquiry' 跟追问混了，task_type 改正
            token_input=usage.prompt_tokens if usage else None,
            token_output=usage.completion_tokens if usage else None,
            output_result=result,
            model_name=model_options.get("model_name"),  # 审计 #7
        )
        return result
    except Exception as exc:
        logger.exception("ai.diagnosis_suggestion: failed err=%s", exc)
        # degraded=True 让前端区分"AI 故障"和"真的没有建议"（2026-06-11）
        return {"diagnoses": [], "degraded": True}
