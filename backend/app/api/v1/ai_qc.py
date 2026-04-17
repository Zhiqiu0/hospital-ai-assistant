"""
AI 质控路由（/api/v1/ai/quick-qc 等）

端点列表：
  POST   /quick-qc       规则引擎 + LLM 双重质控，SSE 流式返回（规则结果立即推送，LLM 结果追加）
  POST   /qc-fix         针对单条质控问题生成修复文本
  POST   /grade-score    甲级病历评分（0-100 分及逐项扣分明细）
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import asyncio
import json
import logging

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.database import get_db
from app.schemas.ai_request import GradeScoreRequest, QCFixRequest, QuickQCRequest
from app.services.ai.ai_utils import get_active_prompt, safe_format
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import GRADE_SCORE_PROMPT, QC_FIX_PROMPT, QC_PROMPT, RECORD_TYPE_LABELS
from app.services.ai.task_logger import calc_grade_score, log_ai_task, save_qc_issues
from app.services.rule_engine.completeness_rules import check_completeness
from app.services.rule_engine.insurance_rules import check_insurance_risk

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/quick-qc")
async def quick_qc(
    req: QuickQCRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """SSE 流式质控：规则引擎结果立即推送，LLM 质量建议追加推送。

    事件格式（每行 data: <json>\\n\\n）：
      rule_issues  — 规则引擎结果，含评分，立即返回
      llm_issues   — LLM 质量建议，LLM 完成后返回
      done         — 汇总信息，流结束
      error        — LLM 调用失败（规则引擎结果已在 rule_issues 中）
    """
    async def generate():
        if not req.content.strip():
            yield f'data: {json.dumps({"type": "done", "issues": [], "summary": "病历内容为空", "pass": False, "grade_score": 0, "grade_level": "丙级"})}\n\n'
            return

        is_inpatient = (req.record_type or "outpatient") != "outpatient"

        # 预取 DB 配置（快速，顺序执行避免 session 并发问题）
        db_prompt = await get_active_prompt(db, "qc")
        model_options = await get_model_options(db, "qc")

        # 构建 LLM prompt（纯内存操作，瞬时）
        record_type_label = RECORD_TYPE_LABELS.get(req.record_type or "outpatient", "门诊病历")
        template = db_prompt or QC_PROMPT
        prompt = safe_format(template, record_type=record_type_label, content=req.content)

        # 启动 LLM 任务（后台，不阻塞规则引擎）
        llm_task = asyncio.create_task(
            llm_client.chat_json_stream(
                [{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=model_options["max_tokens"],
                model_name=model_options["model_name"],
            )
        )

        # 规则引擎顺序执行（共享 db session，避免并发问题）
        rule_issues = await check_completeness(
            record_text=req.content,
            db=db,
            is_inpatient=is_inpatient,
            is_first_visit=req.is_first_visit if req.is_first_visit is not None else True,
            patient_gender=req.patient_gender or "",
        )
        insurance_issues = await check_insurance_risk(req.content, db)

        insurance_tagged = [{**i, "source": "rule"} for i in insurance_issues]
        rule_score, rule_level = calc_grade_score(rule_issues + insurance_tagged)
        blocking_count = len(rule_issues) + len(insurance_tagged)

        # 立即推送规则引擎结果（此时 LLM 已并行跑了 0.5-1s）
        yield f'data: {json.dumps({"type": "rule_issues", "issues": rule_issues + insurance_tagged, "pass": blocking_count == 0, "grade_score": rule_score, "grade_level": rule_level})}\n\n'

        # 等待 LLM 完成
        try:
            result = await llm_task
            usage = llm_client._last_usage
            task_id = await log_ai_task(
                "qc",
                token_input=usage.prompt_tokens if usage else 0,
                token_output=usage.completion_tokens if usage else 0,
            )

            rule_fields = {i.get("field_name") for i in rule_issues}
            llm_issues = [
                {**i, "source": "llm"}
                for i in result.get("issues", [])
                if i.get("field_name") not in rule_fields
            ]

            all_issues = rule_issues + insurance_tagged + llm_issues
            await save_qc_issues(task_id, all_issues, encounter_id=req.encounter_id)

            summary_parts = []
            if blocking_count == 0:
                summary_parts.append("结构检查全部通过（100分）")
            else:
                summary_parts.append(f"结构问题 {blocking_count} 项需修复")
            if llm_issues:
                summary_parts.append(f"质量建议 {len(llm_issues)} 条")

            yield f'data: {json.dumps({"type": "llm_issues", "issues": llm_issues})}\n\n'
            yield f'data: {json.dumps({"type": "done", "summary": "，".join(summary_parts), "pass": blocking_count == 0, "grade_score": rule_score, "grade_level": rule_level})}\n\n'

        except Exception as exc:
            llm_task.cancel()
            err_msg = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.error("quick_qc LLM failed: %s", err_msg)
            summary_parts = []
            if blocking_count == 0:
                summary_parts.append("结构检查全部通过")
            else:
                summary_parts.append(f"结构问题 {blocking_count} 项需修复")
            summary_parts.append("AI质量分析失败，仅返回规则引擎结果")
            yield f'data: {json.dumps({"type": "done", "summary": "，".join(summary_parts), "pass": blocking_count == 0, "grade_score": rule_score, "grade_level": rule_level})}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/qc-fix")
async def qc_fix(
    req: QCFixRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """针对单条质控问题生成修复文本（非流式）。"""
    prompt = safe_format(
        QC_FIX_PROMPT,
        field_name=req.field_name or "未知字段",
        issue_description=req.issue_description or "",
        suggestion=req.suggestion or "",
        current_record=req.current_record[:800] if req.current_record else "（空）",
        chief_complaint=req.chief_complaint or "未填写",
        history=req.history_present_illness or "未填写",
    )
    try:
        model_options = await get_model_options(db, "qc")
        content = await llm_client.chat(
            [{"role": "user", "content": prompt}],
            temperature=model_options["temperature"],
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "qc",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
        )
        return {"fix_text": content.strip()}
    except Exception as exc:
        logger.error("qc_fix failed: %s", exc, exc_info=True)
        return {"fix_text": req.suggestion or ""}


@router.post("/grade-score")
async def grade_score(
    req: GradeScoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """甲级病历评分：返回预估得分（0-100）、病历等级及逐项扣分明细。"""
    if not req.content.strip():
        return {"grade_score": 0, "grade_level": "丙级", "issues": [], "summary": "病历内容为空，无法评分"}

    is_inpatient = (req.record_type or "admission_note") != "outpatient"
    rule_issues = await check_completeness(
        record_text=req.content,
        db=db,
        is_inpatient=is_inpatient,
        patient_gender=req.patient_gender or "",
    )

    record_type_label = RECORD_TYPE_LABELS.get(req.record_type or "admission_note", "入院记录")
    prompt = GRADE_SCORE_PROMPT.format(record_type=record_type_label, content=req.content)

    try:
        model_options = await get_model_options(db, "qc")
        llm_result = await llm_client.chat_json_stream(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
        usage = llm_client._last_usage
        await log_ai_task(
            "qc",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
        )

        deductions = llm_result.get("deductions", [])
        rule_field_names = {d.get("field_name") for d in deductions}
        for rule_issue in rule_issues:
            if rule_issue.get("field_name") not in rule_field_names:
                deductions.append({
                    "category": "完整性（规则引擎）",
                    "field_name": rule_issue["field_name"],
                    "deduct_points": 2.0 if rule_issue["risk_level"] == "high" else 1.0,
                    "risk_level": rule_issue["risk_level"],
                    "issue_description": rule_issue["issue_description"],
                    "suggestion": rule_issue["suggestion"],
                })

        estimated = llm_result.get("estimated_score", 100)
        grade_level = llm_result.get("grade_level", "")
        if not grade_level:
            if estimated >= 90:
                grade_level = "甲级"
            elif estimated >= 75:
                grade_level = "乙级"
            else:
                grade_level = "丙级"

        return {
            "grade_score": estimated,
            "grade_level": grade_level,
            "deductions": deductions,
            "strengths": llm_result.get("strengths", []),
            "issues": [
                {
                    "risk_level": d.get("risk_level", "medium"),
                    "field_name": d.get("field_name", ""),
                    "issue_description": d.get("issue_description", ""),
                    "suggestion": d.get("suggestion", ""),
                    "score_impact": f"-{d.get('deduct_points', 0)}分",
                }
                for d in deductions
            ],
            "summary": llm_result.get("summary", ""),
        }
    except Exception as exc:
        logger.error("grade_score failed: %s", exc, exc_info=True)
        score_val, level = calc_grade_score(rule_issues)
        return {
            "grade_score": score_val,
            "grade_level": level,
            "deductions": [],
            "strengths": [],
            "issues": rule_issues,
            "summary": f"AI评分分析失败，已基于规则引擎估算（预估{score_val}分）",
        }
