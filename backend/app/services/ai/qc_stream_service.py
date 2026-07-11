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

拆分（超标文件拆分：331 行 → 本门面 + _qc_rubric + _qc_ops）：
  - _qc_rubric ：_INPATIENT_RECORD_TYPES / _select_rubric / _deductions_to_issues
  - _qc_ops    ：run_qc_fix / run_grade_score（两个同步端点）
兼容：上述符号全部从本模块 re-export，
      `qc_stream_service.run_qc_fix(...)` 与 `from ...qc_stream_service import _select_rubric`
      等既有用法保持可用。
"""

import asyncio
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.ai_request import QuickQCRequest, extract_inquiry_dict
from app.services.ai.ai_utils import safe_format
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import QC_PROMPT, RECORD_TYPE_LABELS
from app.services.ai.task_logger import log_ai_task, save_qc_issues
from app.services.qc_engine.checker import build_context
from app.services.qc_engine.scorer import score
from app.services.rule_engine.insurance_rules import check_insurance_risk

# re-export：评分表路由/扣分映射与两个同步端点拆到子模块，保持原导入路径可用
from app.services.ai._qc_rubric import (  # noqa: F401
    _INPATIENT_RECORD_TYPES,
    _deductions_to_issues,
    _select_rubric,
)
from app.services.ai._qc_ops import run_grade_score, run_qc_fix  # noqa: F401


logger = logging.getLogger(__name__)


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
