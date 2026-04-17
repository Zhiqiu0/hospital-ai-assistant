"""
质控问题路由（/api/v1/qc/*）

端点列表：
  PATCH /{issue_id}  更新单条质控问题状态（resolved / ignored）

此路由供前端质控面板（QCIssuePanel）调用，
医生标记问题为"已解决"或"已忽略"后，面板刷新问题状态显示。
质控问题的创建由 AI 质控服务（ai_qc.py）和规则引擎自动完成，
不在此路由暴露创建接口。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.schemas.qc import QCIssueStatusUpdate
from app.services.qc_service import QCIssueService

router = APIRouter()


@router.patch("/{issue_id}")
async def update_issue_status(
    issue_id: str,
    data: QCIssueStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新质控问题的处理状态（resolved / ignored）。

    注意：此端点不校验质控问题归属（issue 归属哪个医生），
    权限控制依赖接诊工作台的整体访问控制（只有在工作台内才能看到问题列表）。
    如需加强，可通过 issue → medical_record → encounter → doctor_id 联表校验。
    """
    service = QCIssueService(db)
    return await service.update_status(issue_id, data.status)
