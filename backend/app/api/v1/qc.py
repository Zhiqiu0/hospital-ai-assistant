from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.qc import QCIssueStatusUpdate
from app.services.qc_service import QCIssueService
from app.core.security import get_current_user

router = APIRouter()


@router.patch("/{issue_id}")
async def update_issue_status(
    issue_id: str,
    data: QCIssueStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    service = QCIssueService(db)
    return await service.update_status(issue_id, data.status)
