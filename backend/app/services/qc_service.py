"""
质控问题服务（app/services/qc_service.py）

职责：
  封装质控问题（QCIssue）的状态管理操作：
  - update_status : 将质控问题标记为"已解决"或"已忽略"

QCIssue 来源：
  质控问题由两种途径产生：
  1. 规则引擎（rule_engine/）扫描生成 —— source='rule'
  2. AI 大模型质控（ai/qc_service.py）生成 —— source='llm'
  本服务只管理状态流转，不感知问题来源。

状态流转：
  pending（待处理）→ resolved（已解决）：医生修复了病历中的问题
  pending（待处理）→ ignored（已忽略）：医生主动忽略（有合理原因不修复）
"""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medical_record import QCIssue


class QCIssueService:
    """质控问题数据访问服务，封装质控问题状态管理。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_status(self, issue_id: str, status: str):
        """更新质控问题的处理状态。

        当 status='resolved' 时，同时记录 resolved_at 时间戳，
        用于统计医生平均质控响应时间（运营分析场景）。

        Args:
            issue_id: 质控问题 ID（QCIssue.id）。
            status:   新状态，可选值：
                      - "resolved" : 问题已修复
                      - "ignored"  : 问题已忽略

        Returns:
            {"ok": True}

        Raises:
            HTTPException(404): 质控问题不存在。
        """
        result = await self.db.execute(select(QCIssue).where(QCIssue.id == issue_id))
        issue = result.scalar_one_or_none()
        if not issue:
            raise HTTPException(status_code=404, detail="质控问题不存在")

        issue.status = status
        if status == "resolved":
            # 记录解决时间戳，用于质控响应时间统计
            issue.resolved_at = datetime.now()

        await self.db.commit()
        return {"ok": True}
