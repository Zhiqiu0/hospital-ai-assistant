"""
AI 任务日志工具（Task Logger）

职责：
  将 AI 调用结果异步持久化到数据库，与主请求事务解耦。
  提供三个纯工具函数，供 AI 路由层调用：

  - log_ai_task     : 写 AITask 记录（独立 DB 会话，不阻塞主事务）
  - save_qc_issues  : 持久化质控问题列表到 qc_issues 表
  - calc_grade_score: 根据质控问题列表计算甲级评分及等级

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
) -> str:
    """将一次 AI 调用写入 ai_tasks 表，使用独立 DB 会话避免污染主事务。

    Args:
        task_type:    任务类型，如 "qc"、"generate"、"polish" 等。
        token_input:  本次调用消耗的输入 token 数；无法获取时传 0。
        token_output: 本次调用消耗的输出 token 数；无法获取时传 0。

    Returns:
        新建 AITask 记录的 UUID，供后续 save_qc_issues 关联使用。
    """
    task_id = generate_uuid()
    async with AsyncSessionLocal() as db:
        task = AITask(
            id=task_id,
            task_type=task_type,
            status="done",
            token_input=token_input,
            token_output=token_output,
            model_name=llm_client.model,
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


def calc_grade_score(issues: list[dict]) -> tuple[float, str]:
    """根据质控问题列表计算甲级评分及病历等级。

    扣分规则（参考浙江省病历质量评分标准）：
      - 规则表中有 score_impact（如 "-2分"）→ 按规则表扣分
      - 含"单项否决"/"否决"的描述 → 扣 10 分
      - risk_level == "high"   → 扣 3 分
      - risk_level == "medium" → 扣 1.5 分
      - risk_level == "low"    → 扣 0.5 分

    等级划分：
      ≥ 90 分 → 甲级
      75-89 分 → 乙级
      < 75 分  → 丙级

    Args:
        issues: 质控问题字典列表，每项含 risk_level / issue_description / score_impact。

    Returns:
        (score_float, level_str) 元组，score_float 为 0-100 浮点数（保留实际精度）。
    """
    import re as _re

    score = 100.0
    for issue in issues:
        risk = issue.get("risk_level", "low")
        desc = issue.get("issue_description", "")
        # 优先读规则表里预设的 score_impact（格式如 "-2分"、"-0.5分"）
        si = issue.get("score_impact", "")
        match = _re.search(r"-(\d+(?:\.\d+)?)", si) if si else None
        if match:
            score -= float(match.group(1))
        elif "单项否决" in desc or "否决" in desc:
            score -= 10
        elif risk == "high":
            score -= 3
        elif risk == "medium":
            score -= 1.5
        else:
            score -= 0.5

    score = max(0.0, score)
    if score >= 90:
        level = "甲级"
    elif score >= 75:
        level = "乙级"
    else:
        level = "丙级"
    return score, level
