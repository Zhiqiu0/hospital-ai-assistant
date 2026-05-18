"""
AI 质控 SSE/在线业务服务（services/ai/qc_stream_service.py）

抽自 api/v1/ai_qc.py 的三个工作台在线端点：
  - run_quick_qc_stream()  Rubric 评分（标准驱动）+ LLM 质量建议（旁路提示）
  - run_qc_fix()           单条质控问题的修复文本生成
  - run_grade_score()      Rubric 评分（与 quick_qc_stream 共用引擎）

L3 治本路线（2026-05-18）：
  - 评分由浙江省卫健委 PDF 法定标准代码常量驱动（qc_engine.rubrics.*）
  - LLM 仅输出"质量建议"（旁路提示），**不参与总分计算**
  - 等级判定：门诊"合格/不合格"，住院"甲/乙/丙级"，按 PDF 注明阈值

路由层只负责：SSE 事件 JSON 序列化、鉴权、审计日志、HTTP 响应包装。
"""

import asyncio
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.ai_request import (
    GradeScoreRequest,
    QCFixRequest,
    QuickQCRequest,
    extract_inquiry_dict,
)
from app.services.ai.ai_utils import safe_format
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import QC_FIX_PROMPT, QC_PROMPT, RECORD_TYPE_LABELS
from app.services.ai.task_logger import log_ai_task, save_qc_issues
from app.services.qc_engine.checker import build_context
from app.services.qc_engine.rubric import Rubric
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023,
)
from app.services.qc_engine.scorer import ScoreReport, score
from app.services.rule_engine.insurance_rules import check_insurance_risk


logger = logging.getLogger(__name__)


def _select_rubric(record_type: str | None) -> Rubric:
    """按 record_type 选择对应法定评分表。

    住院 Rubric 待下一期落地（rubrics/zj_inpatient_2021.py），
    暂时回退到门急诊 Rubric——评分仍按浙江省标准跑（不会因为是住院类型就 100 分）。
    """
    rt = record_type or "outpatient"
    if rt in ("outpatient", "emergency"):
        return ZJ_OUTPATIENT_EMERGENCY_V2023
    # 住院系列暂时复用门急诊 Rubric（占位）。下期接入 ZJ_INPATIENT_V2021 后切换。
    return ZJ_OUTPATIENT_EMERGENCY_V2023


def _deductions_to_issues(report: ScoreReport) -> list[dict]:
    """ScoreReport 扣分列表 → 前端 qcIssues 兼容结构。

    前端依赖的字段（保持兼容）：
      - risk_level: high/medium/low（按扣分值粗映射）
      - field_name: 大项名（用于行级"已写入"修复）
      - issue_description / suggestion / score_impact
      - source: "rule"（必修复，参与等级判定）/ "llm"（旁路建议）
    """
    issues: list[dict] = []
    for d in report.deductions:
        # 扣分值 → 风险等级（用于前端按红/黄/灰分组显示）
        if d.is_veto or d.points >= 5:
            level = "high"
        elif d.points >= 2:
            level = "medium"
        else:
            level = "low"
        issues.append({
            "risk_level": level,
            "field_name": d.item_name,
            "rule_code": d.rule_code,
            "issue_description": d.description,
            "suggestion": d.description,  # PDF 扣分说明本身即为修复指引
            "score_impact": f"-{d.points}分",
            "is_veto": d.is_veto,
            "source": "rule",
        })
    return issues


async def run_quick_qc_stream(
    db: AsyncSession, req: QuickQCRequest
) -> AsyncGenerator[dict, None]:
    """双路并行质控：Rubric 评分先产出，LLM 质量建议异步追加。

    事件 dict（路由层包成 SSE `data: <json>\\n\\n`）：
      {'type': 'rule_issues', issues, pass, grade_score, grade_level, score_report}
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
            "grade_level": "不合格",
            "must_fix_count": 0,
        }
        return

    # 选 Rubric + 构造上下文（FHIR 三资源分层）
    rubric = _select_rubric(req.record_type)
    ctx = build_context(
        req.content,
        record_type=req.record_type or "outpatient",
        is_first_visit=req.is_first_visit if req.is_first_visit is not None else True,
        # 患者基础信息——独立成 PatientMeta，不再串到 inquiry 字典
        patient_name=req.patient_name or "",
        patient_gender=req.patient_gender or "",
        patient_age=req.patient_age or "",
        inquiry=extract_inquiry_dict(req),
    )

    # 并行启动 LLM 质量建议（用旧 QC_PROMPT，输出 issues[] 列表；不参与总分）
    model_options = await get_model_options(db, "qc")
    record_type_label = RECORD_TYPE_LABELS.get(req.record_type or "outpatient", "门诊病历")
    llm_prompt = safe_format(QC_PROMPT, record_type=record_type_label, content=req.content)
    llm_task = asyncio.create_task(
        llm_client.chat_json_stream(
            [{"role": "user", "content": llm_prompt}],
            temperature=0,
            max_tokens=model_options["max_tokens"],
            model_name=model_options["model_name"],
        )
    )

    # Rubric 评分（同步执行，毫秒级）
    report = score(rubric, ctx)
    rule_issues = _deductions_to_issues(report)

    # 医保风险规则保留（这是商保审计层，不在浙江省评分标准内但作为附加 issue 显示）
    insurance_issues = await check_insurance_risk(req.content, db)
    insurance_tagged = [{**i, "source": "rule"} for i in insurance_issues]

    must_fix_count = len(rule_issues) + len(insurance_tagged)

    yield {
        "type": "rule_issues",
        "issues": rule_issues + insurance_tagged,
        "pass": report.passed,
        "grade_score": report.score,
        "grade_level": report.grade,
        "must_fix_count": must_fix_count,
        # 完整评分报告供前端 PDF 四列扣分明细使用
        "score_report": report.to_dict(),
    }

    try:
        llm_result = await llm_task
        usage = llm_client._last_usage
        task_id = await log_ai_task(
            "qc",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
        )

        # LLM 建议去重（避免与 rule 引擎扣分项重复）
        rule_fields = {i.get("field_name") for i in rule_issues}
        llm_issues = [
            {**i, "source": "llm"}
            for i in (llm_result.get("issues", []) or [])
            if i.get("field_name") not in rule_fields
        ]

        all_issues = rule_issues + insurance_tagged + llm_issues
        await save_qc_issues(task_id, all_issues, encounter_id=req.encounter_id)

        summary_parts: list[str] = []
        if report.passed:
            summary_parts.append(f"质控通过（{report.score:.0f} 分 {report.grade}）")
        else:
            summary_parts.append(
                f"{report.score:.0f} 分（{report.grade}），结构问题 {len(rule_issues)} 项需修复"
            )
        if llm_issues:
            summary_parts.append(f"质量建议 {len(llm_issues)} 条")

        yield {"type": "llm_issues", "issues": llm_issues}
        yield {
            "type": "done",
            "summary": "，".join(summary_parts),
            "pass": report.passed,
            "grade_score": report.score,
            "grade_level": report.grade,
            "must_fix_count": must_fix_count,
        }
    except Exception as exc:
        llm_task.cancel()
        err_msg = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.error("quick_qc LLM failed: %s", err_msg)
        # LLM 失败不影响主流程：Rubric 评分已经产出，质量建议可缺
        summary_parts: list[str] = []
        if report.passed:
            summary_parts.append(f"质控通过（{report.score:.0f} 分 {report.grade}）")
        else:
            summary_parts.append(
                f"{report.score:.0f} 分（{report.grade}），结构问题 {len(rule_issues)} 项需修复"
            )
        summary_parts.append("AI 质量分析失败，仅返回规则引擎结果")
        yield {
            "type": "done",
            "summary": "，".join(summary_parts),
            "pass": report.passed,
            "grade_score": report.score,
            "grade_level": report.grade,
            "must_fix_count": must_fix_count,
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
    """病历评分（Rubric 主评，与 quick_qc_stream 共用引擎）。

    与 quick_qc_stream 区别：本接口是同步返回（非 SSE），不并行调 LLM 建议。
    适合"出具最终病历前再跑一次完整评分"场景。
    """
    if not req.content.strip():
        return {
            "grade_score": 0,
            "grade_level": "不合格",
            "must_fix_count": 0,
            "issues": [],
            "summary": "病历内容为空，无法评分",
        }

    rubric = _select_rubric(req.record_type)
    ctx = build_context(
        req.content,
        record_type=req.record_type or "outpatient",
        # 患者基础信息——独立成 PatientMeta，不再串到 inquiry 字典
        patient_name=req.patient_name or "",
        patient_gender=req.patient_gender or "",
        patient_age=req.patient_age or "",
        inquiry=extract_inquiry_dict(req),
    )
    report = score(rubric, ctx)
    issues = _deductions_to_issues(report)

    logger.info(
        "ai.qc_grade: done score=%s grade=%s deductions=%d",
        report.score, report.grade, len(report.deductions),
    )
    return {
        "grade_score": report.score,
        "grade_level": report.grade,
        "must_fix_count": len(issues),
        "issues": issues,
        "score_report": report.to_dict(),
        "summary": (
            f"{report.score:.0f} 分（{report.grade}）"
            if report.passed
            else f"{report.score:.0f} 分（{report.grade}），共扣 {report.total_deducted:.0f} 分"
        ),
    }
