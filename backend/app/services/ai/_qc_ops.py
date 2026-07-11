"""
AI 质控——单条修复 + 同步评分（services/ai/_qc_ops.py）

从 qc_stream_service.py 拆出的两个非 SSE 端点业务：
  - run_qc_fix     ：单条质控问题的修复文本生成
  - run_grade_score：病历评分（Rubric 主评，与 quick_qc_stream 共用引擎）

拆分目的：把两个同步返回的端点从 SSE 主流程剥离，主文件专注 quick_qc_stream。
行为与原实现完全一致，仅做机械搬迁。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.ai_request import (
    GradeScoreRequest,
    QCFixRequest,
    extract_inquiry_dict,
)
from app.services.ai._qc_rubric import _deductions_to_issues, _select_rubric
from app.services.ai.ai_utils import safe_format
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import QC_FIX_PROMPT
from app.services.ai.task_logger import log_ai_task
from app.services.qc_engine.checker import build_context
from app.services.qc_engine.scorer import score

logger = logging.getLogger(__name__)


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
        # 连接池护栏：模型配置已读完，进入最长 270s 的 LLM 调用前先 commit 结束
        # 只读事务、把连接还回池，避免长 await 期间白占一条池连接。
        await db.commit()
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
