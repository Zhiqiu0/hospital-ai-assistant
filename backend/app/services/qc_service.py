from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.medical_record import QCIssue
from fastapi import HTTPException


class QCIssueService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def update_status(self, issue_id: str, status: str):
        result = await self.db.execute(select(QCIssue).where(QCIssue.id == issue_id))
        issue = result.scalar_one_or_none()
        if not issue:
            raise HTTPException(status_code=404, detail="质控问题不存在")
        issue.status = status
        if status == "resolved":
            from datetime import datetime
            issue.resolved_at = datetime.now()
        await self.db.commit()
        return {"message": "更新成功"}
