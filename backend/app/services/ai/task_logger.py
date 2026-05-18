"""
AI 任务日志工具（Task Logger）

职责：
  将 AI 调用结果异步持久化到数据库，与主请求事务解耦。
  提供三个纯工具函数，供 AI 路由层调用：

  - log_ai_task     : 写 AITask 记录（独立 DB 会话，不阻塞主事务）
  - save_qc_issues  : 持久化质控问题列表到 qc_issues 表

L3 治本（2026-05-18）：
  旧 calc_grade_score 已删——评分由 qc_engine.scorer.score() 驱动，
  按浙江省卫健委 PDF 1:1 标准计算，不再用本模块自创的扣分规则。

设计说明：
  使用独立 AsyncSessionLocal 会话而非主请求的 db 参数，目的是让日志写入
  不受主事务的回滚/提交影响——即使主业务失败，日志记录仍可尝试保存。
"""

import logging
from typing import Optional

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.base import generate_uuid
from app.models.medical_record import AITask, MedicalRecord, QCIssue
from app.services.ai.llm_client import llm_client

logger = logging.getLogger(__name__)


async def log_ai_task(
    task_type: str,
    token_input: int = 0,
    token_output: int = 0,
    output_result: Optional[dict] = None,
) -> str:
    """将一次 AI 调用写入 ai_tasks 表，使用独立 DB 会话避免污染主事务。

    encounter_id / medical_record_id 从 RequestContext contextvar 自动读取
    （路由层在调 AI service 前必须先 bind_encounter_context），调用方不再
    需要层层传参。这是合规底线：每条 AI 任务都能追溯到具体接诊。

    Args:
        task_type:     任务类型，如 "qc"、"generate"、"polish" 等。
        token_input:   本次调用消耗的输入 token 数；无法获取时传 0。
        token_output:  本次调用消耗的输出 token 数；无法获取时传 0。
        output_result: LLM 返回的 JSON 结果。snapshot 恢复时能拿回前端，
                       让医生 logout 重登后追问/检查/诊断建议都还在。

    Returns:
        新建 AITask 记录的 UUID，供后续 save_qc_issues 关联使用。
    """
    # 从请求 context 读接诊维度——若路由层未 bind，则字段为 NULL（少数
    # 内部调用场景如 admin 后台批量任务可接受，业务路径必须 bind）
    from app.core.request_context import get_encounter_id, get_medical_record_id
    encounter_id = get_encounter_id()
    medical_record_id = get_medical_record_id()

    task_id = generate_uuid()
    async with AsyncSessionLocal() as db:
        task = AITask(
            id=task_id,
            task_type=task_type,
            status="done",
            token_input=token_input,
            token_output=token_output,
            model_name=llm_client.model,
            encounter_id=encounter_id,
            medical_record_id=medical_record_id,
            output_result=output_result,
        )
        db.add(task)
        try:
            await db.commit()
        except Exception as exc:
            # 日志写入失败不影响主流程，仅记录错误供排查
            logger.error("ai_task.log: commit_failed err=%s", exc)
    return task_id


async def save_qc_issues(
    task_id: str,
    issues: list[dict],
    encounter_id: Optional[str] = None,
) -> None:
    """将质控问题列表持久化到 qc_issues 表。

    Args:
        task_id:      关联的 AITask.id，用于追溯本次 AI 调用。
        issues:       质控问题字典列表，每项应包含：
                        - source        : "rule"（规则引擎）或 "llm"（AI 建议）
                        - issue_type    : "completeness"/"insurance"/"format" 等
                        - risk_level    : "high"/"medium"/"low"
                        - field_name    : 对应的病历字段名
                        - issue_description: 问题描述
                        - suggestion    : 修复建议
        encounter_id: 可选接诊 ID，用于关联最新的 MedicalRecord 记录。

    注意：
        issue 字典中的 source 字段由调用方在构造问题时已明确标注
        （规则引擎问题标 "rule"，LLM 问题标 "llm"），此处直接使用，
        不再重新推断，避免覆盖正确值。
    """
    if not issues:
        return

    async with AsyncSessionLocal() as db:
        # 尝试通过 encounter_id 找到最新病历，建立关联（可选，找不到不阻塞）
        medical_record_id: Optional[str] = None
        if encounter_id:
            result = await db.execute(
                select(MedicalRecord)
                .where(MedicalRecord.encounter_id == encounter_id)
                .order_by(MedicalRecord.created_at.desc())
                .limit(1)
            )
            rec = result.scalar_one_or_none()
            if rec:
                medical_record_id = rec.id

        for issue in issues:
            # BUG FIX: 原代码用 issue_type 是否存在来推断 source，
            # 导致有 issue_type 的 LLM 问题被错存为 "rule"。
            # 正确做法：直接使用调用方已设置的 source 字段。
            source = issue.get("source") or "rule"

            qc = QCIssue(
                ai_task_id=task_id,
                medical_record_id=medical_record_id,
                issue_type=issue.get("issue_type") or "quality",
                risk_level=issue.get("risk_level") or "medium",
                field_name=issue.get("field_name"),
                issue_description=issue.get("issue_description") or "",
                suggestion=issue.get("suggestion"),
                source=source,
            )
            db.add(qc)

        try:
            await db.commit()
        except Exception as exc:
            # 持久化失败不影响前端实时展示（前端通过 SSE 已收到结果）
            logger.error("qc_issues.save: commit_failed err=%s", exc)


# L3 治本路线（2026-05-18）：
#   评分由 qc_engine.scorer.score() 驱动（浙江省 PDF 1:1 法定标准）。
#   原 calc_grade_score 用了"自创扣分规则"（risk_level 浮点扣分 + 75/90 阈值），
#   不符合 PDF 注 5 / 备注 8 的法定阈值。整函数已删除——所有调用方切到
#   qc_engine 的 ScoreReport 模型。
