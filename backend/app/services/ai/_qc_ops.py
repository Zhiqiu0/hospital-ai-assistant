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
from app.services.ai._qc_rubric import _deductions_to_issues, _select_rubric, get_rubric_key
from app.services.ai.ai_utils import safe_format
from app.services.ai.llm_client import LLMServiceError, llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.output_guards import strip_unsubstantiated_vitals
from app.services.ai.prompts import QC_FIX_PROMPT
from app.services.ai.task_logger import log_ai_task, save_qc_report
from app.services.ai._qc_frontpage import load_front_page
from app.services.qc_engine.checker import build_context
from app.services.qc_engine.scorer import score

logger = logging.getLogger(__name__)


async def run_qc_fix(db: AsyncSession, req: QCFixRequest) -> dict:
    """单条质控问题的修复文本。

    返回 {"fix_text", "degraded", "error"}：LLM 失败时保守回退原 suggestion，
    但必须带 degraded=True 让医生知道"这不是 AI 写的修复"（2026-08-28 体检：
    此前静默回退，医生把建议原文误当 AI 修复采纳）。error 为医生可读原因
    （欠费/限流等，来自 LLMServiceError）。
    """
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
        model_options = get_model_options("qc")
        # 连接池护栏：进入最长 270s 的 LLM 调用前先 commit 结束本请求此前的只读事务（若有）、
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
            model_name=model_options.get("model_name"),  # 真实模型，非全局默认（审计 #7）
        )
        # 数值真实性守卫（2026-08-11 审计修复）：与批量修复路径同款确定性后校验。
        # source_text 只取医生录入字段（current_record + 主诉 + 现病史），排除
        # issue_description/suggestion——它们可能含 LLM 生成内容，不能当出处。
        # 编造的体征数值被剔除后若整段变空，前端"写入病历"按钮因 fix_text 空自动禁用。
        source_text = "\n".join(
            str(x) for x in (
                req.current_record, req.chief_complaint, req.history_present_illness
            ) if x
        )
        cleaned = strip_unsubstantiated_vitals(content.strip(), source_text)
        if cleaned != content.strip():
            logger.warning("ai.qc_fix.guard: stripped_fabricated_vitals field=%s",
                           req.field_name)
        # 异己前缀截断（2026-08-22 串写实锤守卫，与批量补全同款）：LLM 偶把
        # 相邻字段（处理意见/复诊建议…）整段拼进单字段的修复文本
        from app.services.ai.supplement_batch_service import _strip_foreign_prefixes
        stripped = _strip_foreign_prefixes(req.field_name or "", cleaned)
        if stripped != cleaned:
            logger.warning("ai.qc_fix.guard: stripped_foreign_prefixes field=%s",
                           req.field_name)
        return {"fix_text": stripped, "degraded": False, "error": None}
    except Exception as exc:
        logger.exception("ai.qc_fix: failed err=%s", exc)
        err = exc.user_message if isinstance(exc, LLMServiceError) else "AI 修复失败"
        return {"fix_text": req.suggestion or "", "degraded": True, "error": err}


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
    # 病案首页结构化数据预取（2026-08-21 阶段3；无 encounter 时首页规则跳过）
    front_page = await load_front_page(db, getattr(req, "encounter_id", None))
    ctx = build_context(
        req.content,
        record_type=req.record_type or "outpatient",
        # 患者基础信息——独立成 PatientMeta，不再串到 inquiry 字典。
        # 2026-08-20：三个字段已正式加进 GradeScoreRequest（此前缺失导致性别/
        # 年龄类规则在本端点永远不触发）；getattr 兜底保留，容忍旧调用方。
        patient_name=getattr(req, "patient_name", "") or "",
        patient_gender=getattr(req, "patient_gender", "") or "",
        patient_age=getattr(req, "patient_age", "") or "",
        # 复诊豁免透传（2026-08-20）：不传则主诉持续时间等规则恒按初诊从严
        is_first_visit=req.is_first_visit if req.is_first_visit is not None else True,
        inquiry=extract_inquiry_dict(req),
        front_page=front_page,
    )
    report = score(rubric, ctx)
    issues = _deductions_to_issues(report)

    # 评分权威落库（2026-08-21 阶段0）：与 quick_qc_stream 同口径写 qc_reports——
    # 本端点此前完全不落库，"出具最终病历前的最后一次评分"恰是最该留痕的一次
    await save_qc_report(
        report.to_dict(),
        deductions=[
            {
                "rule_code": d.rule_code,
                "item_name": d.item_name,
                "target_field": d.target_field,
                "points": d.points,
                "is_veto": d.is_veto,
                "description": d.description,
            }
            for d in report.deductions
        ],
        rubric_key=get_rubric_key(rubric),
        encounter_id=getattr(req, "encounter_id", None),
        record_type=req.record_type,
    )

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
