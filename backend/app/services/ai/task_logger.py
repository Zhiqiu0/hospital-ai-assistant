"""
AI 任务日志工具（Task Logger）

提供三个纯工具函数，供 AI 路由层调用：
  - log_ai_task    : 写 AITask 记录（独立 DB 会话，不阻塞主流程）
  - save_qc_issues : 持久化质控问题列表
  - calc_grade_score: 根据质控问题列表计算甲级评分及等级
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
    """将 AI 调用写入 ai_tasks 表，使用独立 DB 会话避免污染主事务。

    Returns:
        新建任务的 UUID。
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
            logger.error("log_ai_task commit failed: %s", exc)
    return task_id


async def save_qc_issues(
    task_id: str,
    issues: list[dict],
    encounter_id: Optional[str] = None,
) -> None:
    """将质控问题列表持久化到 qc_issues 表。

    Args:
        task_id:     关联的 AITask.id。
        issues:      质控问题字典列表，每项含 risk_level / field_name 等字段。
        encounter_id: 可选的接诊 ID，用于关联病历记录。
    """
    if not issues:
        return

    async with AsyncSessionLocal() as db:
        # 尝试通过 encounter_id 找到最新病历，建立关联
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
            qc = QCIssue(
                ai_task_id=task_id,
                medical_record_id=medical_record_id,
                issue_type=issue.get("issue_type") or "quality",
                risk_level=issue.get("risk_level") or "medium",
                field_name=issue.get("field_name"),
                issue_description=issue.get("issue_description") or "",
                suggestion=issue.get("suggestion"),
                # source 由调用方在 issue 中标注；未标注时按是否有 issue_type 区分
                source="ai" if not issue.get("issue_type") else "rule",
            )
            db.add(qc)

        try:
            await db.commit()
        except Exception as exc:
            logger.error("save_qc_issues commit failed: %s", exc)


def calc_grade_score(issues: list[dict]) -> tuple[int, str]:
    """根据质控问题列表计算甲级评分及病历等级。

    扣分规则（与浙江省评分标准对齐）：
      - high（含"单项否决"）: 扣 10 分；其余 high: 扣 3 分
      - medium: 扣 1.5 分
      - low: 扣 0.5 分

    等级划分：
      ≥90 → 甲级，75-89 → 乙级，<75 → 丙级

    Returns:
        (score_int, level_str)，score_int 为 0-100 的整数。
    """
    import re as _re

    score = 100.0
    for issue in issues:
        risk = issue.get("risk_level", "low")
        desc = issue.get("issue_description", "")
        # 优先用规则表里存的 score_impact（如 "-2分"、"-0.5分"）
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
    score_int = round(score)
    if score_int >= 90:
        level = "甲级"
    elif score_int >= 75:
        level = "乙级"
    else:
        level = "丙级"
    return score_int, level
