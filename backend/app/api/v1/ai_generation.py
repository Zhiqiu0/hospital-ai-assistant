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
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.ai_request import (
    ContinueRequest,
    NormalizeFieldsRequest,
    PolishRequest,
    QuickGenerateRequest,
    SupplementRequest,
)
from app.services.ai.ai_utils import get_active_prompt, safe_format, stream_text
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import (
    CONTINUE_PROMPT,
    POLISH_PROMPT,
    PROMPT_MAP,
    RECORD_TYPE_LABELS,
    SUPPLEMENT_PROMPT,
)

logger = logging.getLogger(__name__)

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
    record_type = req.record_type or "outpatient"
    db_prompt = await get_active_prompt(db, record_type)
    template = db_prompt or PROMPT_MAP.get(record_type, PROMPT_MAP["outpatient"])
    model_options = await get_model_options(db, "generate")

    # 构建住院专项评估段落
    assessment_parts = [
        f"病史陈述者：{req.history_informant}" if req.history_informant else "",
        f"婚育史：{req.marital_history}" if req.marital_history else "",
        f"月经史：{req.menstrual_history}" if req.menstrual_history else "",
        f"家族史：{req.family_history}" if req.family_history else "",
        f"当前用药：{req.current_medications}" if req.current_medications else "",
        f"疼痛评分（NRS）：{req.pain_assessment or '0'}分",
        f"VTE风险：{req.vte_risk}" if req.vte_risk else "",
        f"营养评估：{req.nutrition_assessment}" if req.nutrition_assessment else "",
        f"心理评估：{req.psychology_assessment}" if req.psychology_assessment else "",
        f"康复需求：{req.rehabilitation_assessment}" if req.rehabilitation_assessment else "",
        f"宗教信仰/饮食禁忌：{req.religion_belief}" if req.religion_belief else "",
    ]
    assessment_info = "\n".join(p for p in assessment_parts if p) or "未提供"

    visit_type_label = {"outpatient": "门诊", "emergency": "急诊", "inpatient": "住院"}.get(
        req.visit_type_detail or "outpatient", "门诊"
    )
    visit_nature = "初诊" if req.is_first_visit else "复诊"
    revisit_note = "③复诊患者需记录治疗后症状改变情况；" if not req.is_first_visit else ""
    is_emergency = (req.visit_type_detail or "outpatient") == "emergency"

    emergency_section = (
        f"\n急诊附加：\n  急诊生命体征：{req.physical_exam or '见体格检查'}"
        f"\n  留观记录：{req.observation_notes or '未提供'}"
        f"\n  患者去向：{req.patient_disposition or '未提供'}"
        if is_emergency else ""
    )
    emergency_record_section = (
        "\n【急诊留观记录】\n（记录留观期间病情变化、处理措施及患者去向）"
        if is_emergency else ""
    )
    precautions_val = req.precautions or ""
    precautions_section = f"注意事项：{precautions_val}" if precautions_val else ""

    fmt_kwargs: dict = dict(
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        personal_history=req.personal_history or "未提供",
        physical_exam=req.physical_exam or "未提供",
        auxiliary_exam=req.auxiliary_exam or "未提供",
        initial_impression=req.initial_impression or "未提供",
        patient_name=req.patient_name or "患者",
        patient_gender=req.patient_gender or "未知",
        patient_age=req.patient_age or "未知",
        assessment_info=assessment_info,
        visit_type_label=visit_type_label,
        visit_nature=visit_nature,
        revisit_note=revisit_note,
        tcm_inspection=req.tcm_inspection or "未提供",
        tcm_auscultation=req.tcm_auscultation or "未提供",
        tongue_coating=req.tongue_coating or "未提供",
        pulse_condition=req.pulse_condition or "未提供",
        western_diagnosis=req.western_diagnosis or req.initial_impression or "待明确",
        tcm_disease_diagnosis=req.tcm_disease_diagnosis or "待明确",
        tcm_syndrome_diagnosis=req.tcm_syndrome_diagnosis or "待明确",
        treatment_method=req.treatment_method or "未提供",
        treatment_plan=req.treatment_plan or "未提供",
        followup_advice=req.followup_advice or "未提供",
        precautions=precautions_val or "未提供",
        emergency_section=emergency_section,
        emergency_record_section=emergency_record_section,
        precautions_section=precautions_section,
        visit_time=req.visit_time or "未记录",
        onset_time=req.onset_time or "未记录",
    )

    try:
        prompt = template.format(**fmt_kwargs)
    except KeyError:
        # 自定义 prompt 字段不全时降级为最小集格式化
        prompt = template.format(
            chief_complaint=fmt_kwargs["chief_complaint"],
            history_present_illness=fmt_kwargs["history_present_illness"],
            past_history=fmt_kwargs["past_history"],
            allergy_history=fmt_kwargs["allergy_history"],
            personal_history=fmt_kwargs["personal_history"],
            physical_exam=fmt_kwargs["physical_exam"],
            initial_impression=fmt_kwargs["initial_impression"],
            patient_name=fmt_kwargs["patient_name"],
            patient_gender=fmt_kwargs["patient_gender"],
            patient_age=fmt_kwargs["patient_age"],
            assessment_info=fmt_kwargs["assessment_info"],
            auxiliary_exam=fmt_kwargs["auxiliary_exam"],
        )

    return StreamingResponse(
        stream_text(prompt, task_type="generate", model_options=model_options),
        media_type="text/event-stream",
    )


@router.post("/quick-continue")
async def quick_continue(
    req: ContinueRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """续写病历未完成部分（流式）。"""
    record_type = RECORD_TYPE_LABELS.get(req.record_type or "outpatient", "门诊病历")
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
        physical_exam=req.physical_exam or "未提供",
        initial_impression=req.initial_impression or "未提供",
        current_content=req.current_content or "（暂无内容）",
    )
    model_options = await get_model_options(db, "generate")
    return StreamingResponse(
        stream_text(prompt, task_type="generate", model_options=model_options),
        media_type="text/event-stream",
    )


@router.post("/quick-supplement")
async def quick_supplement(
    req: SupplementRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """根据质控问题一键补全病历（流式）。"""
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
        physical_exam=req.physical_exam or "未提供",
        auxiliary_exam=req.auxiliary_exam or "无",
        initial_impression=req.initial_impression or "未提供",
        onset_time=req.onset_time or "未提供",
        visit_time=req.visit_time or "未提供",
        current_content=req.current_content or "（空）",
        qc_issues=issues_text,
    )
    model_options = await get_model_options(db, "generate")
    return StreamingResponse(
        stream_text(prompt, task_type="generate", model_options=model_options),
        media_type="text/event-stream",
    )


@router.post("/quick-polish")
async def quick_polish(
    req: PolishRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """润色病历（流式）。"""
    db_prompt = await get_active_prompt(db, "polish")
    template = db_prompt or POLISH_PROMPT
    model_options = await get_model_options(db, "polish")
    prompt = safe_format(template, content=req.content)
    return StreamingResponse(
        stream_text(prompt, task_type="polish", model_options=model_options),
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
        logger.error("normalize_fields failed: %s", exc, exc_info=True)
        return {"fields": req.fields}  # 失败时原样返回，不阻塞保存
