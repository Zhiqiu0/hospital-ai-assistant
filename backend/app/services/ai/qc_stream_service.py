"""
AI 质控 SSE/在线业务服务（services/ai/qc_stream_service.py）

抽自 api/v1/ai_qc.py 的三个工作台在线端点：
  - run_quick_qc_stream()  规则引擎 + LLM 双重质控，async generator 产出事件 dict
  - run_qc_fix()           单条质控问题的修复文本生成
  - run_grade_score()      甲级病历评分（规则引擎 + LLM 合并扣分）

与 services/ai/qc_service.py 的 QCService 区别：
  QCService 是后台异步扫描（单次 JSON 响应），本模块是工作台实时交互（SSE + 即时反馈）。

路由层只负责：SSE 事件 JSON 序列化、鉴权、审计日志、HTTP 响应包装。
"""

import asyncio
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.ai_request import GradeScoreRequest, QCFixRequest, QuickQCRequest
from app.services.ai.ai_utils import get_active_prompt, safe_format
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import GRADE_SCORE_PROMPT, QC_FIX_PROMPT, QC_PROMPT, RECORD_TYPE_LABELS
from app.services.ai.task_logger import calc_grade_score, log_ai_task, save_qc_issues
from app.services.rule_engine.completeness_rules import check_completeness
from app.services.rule_engine.insurance_rules import check_insurance_risk


logger = logging.getLogger(__name__)


async def run_quick_qc_stream(
    db: AsyncSession, req: QuickQCRequest
) -> AsyncGenerator[dict, None]:
    """双路并行质控：规则引擎先产出，LLM 异步追加。

    事件 dict（路由层包成 SSE `data: <json>\\n\\n`）：
      {'type': 'rule_issues', issues, pass, grade_score, grade_level}
      {'type': 'llm_issues', issues}
      {'type': 'done', summary, pass, grade_score, grade_level}
    """
    if not req.content.strip():
        yield {
            "type": "done",
            "issues": [],
            "summary": "病历内容为空",
            "pass": False,
            "grade_score": 0,
            "grade_level": "丙级",
        }
        return

    is_inpatient = (req.record_type or "outpatient") != "outpatient"

    db_prompt = await get_active_prompt(db, "qc")
    model_options = await get_model_options(db, "qc")

    record_type_label = RECORD_TYPE_LABELS.get(req.record_type or "outpatient", "门诊病历")
    template = db_prompt or QC_PROMPT
    prompt = safe_format(template, record_type=record_type_label, content=req.content)

    llm_task = asyncio.create_task(
        llm_client.chat_json_stream(
            [{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
    )

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

    yield {
        "type": "rule_issues",
        "issues": rule_issues + insurance_tagged,
        "pass": blocking_count == 0,
        "grade_score": rule_score,
        "grade_level": rule_level,
    }

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

        summary_parts: list[str] = []
        if blocking_count == 0:
            summary_parts.append("结构检查全部通过（100分）")
        else:
            summary_parts.append(f"结构问题 {blocking_count} 项需修复")
        if llm_issues:
            summary_parts.append(f"质量建议 {len(llm_issues)} 条")

        yield {"type": "llm_issues", "issues": llm_issues}
        yield {
            "type": "done",
            "summary": "，".join(summary_parts),
            "pass": blocking_count == 0,
            "grade_score": rule_score,
            "grade_level": rule_level,
        }
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
        yield {
            "type": "done",
            "summary": "，".join(summary_parts),
            "pass": blocking_count == 0,
            "grade_score": rule_score,
            "grade_level": rule_level,
        }


async def run_qc_fix(db: AsyncSession, req: QCFixRequest) -> str:
    """单条质控问题的修复文本；失败返回原 suggestion 作为保守回退。"""
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
        return content.strip()
    except Exception as exc:
        logger.exception("ai.qc_fix: failed err=%s", exc)
        return req.suggestion or ""


async def run_grade_score(db: AsyncSession, req: GradeScoreRequest) -> dict:
    """甲级病历评分（LLM 主评 + 规则引擎扣分补充；LLM 失败退规则引擎兜底）。"""
    if not req.content.strip():
        return {
            "grade_score": 0,
            "grade_level": "丙级",
            "issues": [],
            "summary": "病历内容为空，无法评分",
        }

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

        # 业务里程碑：质控评分完成（监控质控成功率 + 评分分布）
        logger.info(
            "ai.qc_grade: done score=%s level=%s deductions=%d",
            estimated, grade_level, len(deductions),
        )
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
        logger.exception("ai.qc_grade: failed err=%s", exc)
        score_val, level = calc_grade_score(rule_issues)
        return {
            "grade_score": score_val,
            "grade_level": level,
            "deductions": [],
            "strengths": [],
            "issues": rule_issues,
            "summary": f"AI评分分析失败，已基于规则引擎估算（预估{score_val}分）",
        }
