"""
AI 病历生成路由（/api/v1/ai/quick-generate 等）

端点列表：
  POST   /quick-generate      流式生成指定类型病历草稿
  POST   /quick-continue      流式续写未完成病历
  POST   /quick-supplement    根据质控问题一键补全病历（流式）
  POST   /quick-polish        病历润色（流式）
  POST   /normalize-fields    问诊字段规范化（口语→书面）
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import json
import logging
import re

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.database import get_db
from app.services.audit_service import log_action
from app.schemas.ai_request import (
    ContinueRequest,
    NormalizeFieldsRequest,
    PolishRequest,
    QuickGenerateRequest,
    SupplementRequest,
)
from app.services.ai.ai_utils import (
    compose_physical_exam,
    get_active_prompt,
    safe_format,
    stream_text,
    stream_with_lock,
)
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import (
    CONTINUE_PROMPT,
    POLISH_PROMPT,
    RECORD_TYPE_LABELS,
    SUPPLEMENT_PROMPT,
)
from app.services.ai.record_gen_v2_service import stream_record_v2
from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)


async def _acquire_ai_gen_lock(user_id: str, scope: str) -> tuple[str, str]:
    """为 AI 流式生成接口拿锁，已被占用则直接 409。

    锁 key 含 user_id + scope，让同一医生同时只能跑一个生成任务（极少有合理用例
    要并行跑两份病历草稿）；ttl=120s 覆盖正常 LLM 流耗时。
    """
    lock_key = f"lock:ai_gen:{user_id}:{scope}"
    token = await redis_cache.acquire_lock(lock_key, ttl=120)
    if token is None:
        raise HTTPException(
            status_code=429,
            detail="您有一个 AI 生成任务正在进行中，请等待完成后再试",
        )
    return lock_key, token


router = APIRouter()

# 字段英文名 → 中文标签映射（用于 normalize-fields prompt 构建）
_FIELD_LABELS: dict[str, str] = {
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "menstrual_history": "月经史",
    "physical_exam": "体格检查",
    "auxiliary_exam": "辅助检查",
    "initial_impression": "初步诊断",
}


@router.post("/quick-generate")
async def quick_generate(
    req: QuickGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """根据问诊信息流式生成指定类型的病历草稿。"""
    # 把接诊维度写入 RequestContext，下游 log_ai_task 自动取用——
    # 让 ai_tasks.encounter_id 能正确绑定（合规追溯 + snapshot 恢复需要）
    from app.core.request_context import bind_encounter_context
    bind_encounter_context(
        encounter_id=req.encounter_id,
        medical_record_id=req.medical_record_id,
    )

    # 审计：记录医生对哪个病历类型调了 AI 生成（医疗场景合规要求）
    await log_action(
        action="ai_quick_generate",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        detail=f"record_type={req.record_type or 'outpatient'}",
    )
    # 急诊接诊自动选急诊 record_type，除非医生已明确指定其他类型
    is_emergency = (req.visit_type_detail or "outpatient") == "emergency"
    record_type = req.record_type or ("emergency" if is_emergency else "outpatient")

    # L3 新架构：所有病历生成统一走"JSON 模式 → renderer 拼文本 → SSE 推回"
    # 行格式由后端模板严格控制，永远符合 QC 契约。
    # 白名单外的 record_type 由 service 内部抛 error 事件让前端 toast。
    lock_key, lock_token = await _acquire_ai_gen_lock(current_user.id, "generate")
    return StreamingResponse(
        stream_with_lock(
            stream_record_v2(record_type, req, db),
            lock_key, lock_token,
        ),
        media_type="text/event-stream",
    )


@router.post("/quick-continue")
async def quick_continue(
    req: ContinueRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """续写病历未完成部分（流式）。"""
    await log_action(
        action="ai_quick_continue",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        detail=f"record_type={req.record_type or 'outpatient'}",
    )
    record_type = RECORD_TYPE_LABELS.get(req.record_type or "outpatient", "门诊病历")
    composed_physical_exam = compose_physical_exam(
        physical_exam=req.physical_exam,
        temperature=req.temperature,
        pulse=req.pulse,
        respiration=req.respiration,
        bp_systolic=req.bp_systolic,
        bp_diastolic=req.bp_diastolic,
        spo2=req.spo2,
        height=req.height,
        weight=req.weight,
    )
    prompt = CONTINUE_PROMPT.format(
        record_type=record_type,
        patient_name=req.patient_name or "未知",
        patient_gender=req.patient_gender or "未知",
        patient_age=req.patient_age or "未知",
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        personal_history=req.personal_history or "未提供",
        physical_exam=composed_physical_exam or "未提供",
        initial_impression=req.initial_impression or "未提供",
        current_content=req.current_content or "（暂无内容）",
    )
    model_options = await get_model_options(db, "generate")
    lock_key, lock_token = await _acquire_ai_gen_lock(current_user.id, "continue")
    return StreamingResponse(
        stream_with_lock(
            stream_text(prompt, task_type="generate", model_options=model_options),
            lock_key, lock_token,
        ),
        media_type="text/event-stream",
    )


@router.post("/quick-supplement")
async def quick_supplement(
    req: SupplementRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """根据质控问题一键补全病历（流式）。"""
    await log_action(
        action="ai_quick_supplement",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        detail=f"record_type={req.record_type or 'outpatient'} issues_count={len(req.qc_issues or [])}",
    )
    if not req.qc_issues:
        return StreamingResponse(
            iter(['data: {"type":"done"}\n\n']),
            media_type="text/event-stream",
        )

    record_type = RECORD_TYPE_LABELS.get(req.record_type or "outpatient", "门诊病历")
    issues_text = "\n".join(
        f"- [{item.get('risk_level', '').upper()}] {item.get('issue_description', '')}"
        f"（建议：{item.get('suggestion', '')}）"
        for item in req.qc_issues
    )
    composed_physical_exam = compose_physical_exam(
        physical_exam=req.physical_exam,
        temperature=req.temperature,
        pulse=req.pulse,
        respiration=req.respiration,
        bp_systolic=req.bp_systolic,
        bp_diastolic=req.bp_diastolic,
        spo2=req.spo2,
        height=req.height,
        weight=req.weight,
    )
    prompt = SUPPLEMENT_PROMPT.format(
        record_type=record_type,
        patient_name=req.patient_name or "未知",
        patient_gender=req.patient_gender or "未知",
        patient_age=req.patient_age or "未知",
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        personal_history=req.personal_history or "未提供",
        family_history=req.family_history or "未提供",
        physical_exam=composed_physical_exam or "未提供",
        auxiliary_exam=req.auxiliary_exam or "无",
        initial_impression=req.initial_impression or "未提供",
        onset_time=req.onset_time or "未提供",
        visit_time=req.visit_time or "未提供",
        current_content=req.current_content or "（空）",
        qc_issues=issues_text,
    )
    model_options = await get_model_options(db, "generate")
    lock_key, lock_token = await _acquire_ai_gen_lock(current_user.id, "supplement")
    return StreamingResponse(
        stream_with_lock(
            stream_text(prompt, task_type="generate", model_options=model_options),
            lock_key, lock_token,
        ),
        media_type="text/event-stream",
    )


@router.post("/quick-polish")
async def quick_polish(
    req: PolishRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """润色病历（流式）。"""
    await log_action(
        action="ai_quick_polish",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
    )
    db_prompt = await get_active_prompt(db, "polish")
    template = db_prompt or POLISH_PROMPT
    model_options = await get_model_options(db, "polish")
    prompt = safe_format(template, content=req.content)
    lock_key, lock_token = await _acquire_ai_gen_lock(current_user.id, "polish")
    return StreamingResponse(
        stream_with_lock(
            stream_text(prompt, task_type="polish", model_options=model_options),
            lock_key, lock_token,
        ),
        media_type="text/event-stream",
    )


@router.post("/normalize-fields")
async def normalize_fields(
    req: NormalizeFieldsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """将修改的问诊字段规范化（口语→书面，去重，格式统一），返回整理后的字段值。"""
    if not req.fields:
        return {"fields": {}}

    field_lines = "\n".join(
        f"{_FIELD_LABELS.get(k, k)}：{v}"
        for k, v in req.fields.items()
        if v
    )
    prompt = (
        "你是临床病历规范化助手。请对以下问诊字段进行整理，要求：\n"
        "1. 口语转书面医学语言\n"
        "2. 去除重复信息（如同一数值在结构化行和自由文本中重复出现）\n"
        "3. 格式规范，符合医疗文书标准\n"
        "4. 不添加任何未提及的内容，不编造信息\n"
        "5. 每个字段独立整理，保持原有信息量\n\n"
        f"需整理的字段：\n{field_lines}\n\n"
        "请只输出JSON对象，key为字段名（英文），value为整理后的文本：\n"
        '{"chief_complaint": "...", "physical_exam": "...", ...}\n'
        "只输出本次传入的字段，不要输出未传入的字段。"
    )

    try:
        model_options = await get_model_options(db, "generate")
        content = await llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            **(model_options or {}),
        )
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return {"fields": req.fields}
        result = json.loads(match.group())
        return {"fields": {k: result[k] for k in req.fields if k in result and result[k]}}
    except Exception as exc:
        logger.exception("ai.normalize: failed err=%s", exc)
        return {"fields": req.fields}  # 失败时原样返回，不阻塞保存
