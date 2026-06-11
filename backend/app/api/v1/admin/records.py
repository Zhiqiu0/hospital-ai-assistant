"""
管理后台病历管理接口（/api/v1/admin/records/*）

端点列表：
  GET  /                 分页查询所有已签发病历（可按医生 ID 筛选），含患者和医生信息
  POST /{record_id}/revise  管理员修订已签发病历（创建新 RecordVersion，旧版本保留）

仅管理员可访问（require_admin）。
只返回 status='submitted' 的病历（已签发），草稿/生成中的病历不在此展示。
每条病历附带：患者姓名/性别、接诊医生姓名、病历内容预览（前 100 字）。

业务逻辑已下沉到 app/services/admin_record_service.py（2026-06-11 Round 5 迁移），
本文件只保留请求解析 + 鉴权 + 调 service。
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.database import get_db
from app.services.admin_record_service import AdminRecordService

router = APIRouter()


class ReviseRecordRequest(BaseModel):
    """管理员修订病历请求体。

    content: 完整的新病历正文（前端提交修订后的全文，不是 diff）
    revise_reason: 修订理由（必填，写入 audit_logs，永久留痕）
    """

    content: str = Field(min_length=1)
    revise_reason: str = Field(min_length=1, max_length=500)


@router.get("")
async def list_all_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, le=50),
    doctor_id: str = Query(None, description="按医生 UUID 筛选，不传则返回所有医生的病历"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """管理员查看所有已签发病历，可按医生筛选。

    联表查询：MedicalRecord → Encounter → Patient / User，一次获取完整信息。
    """
    service = AdminRecordService(db)
    return await service.list_all_records(page, page_size, doctor_id)


@router.post("/{record_id}/revise")
async def revise_record(
    record_id: str,
    data: ReviseRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """管理员修订已签发病历：创建新 RecordVersion，旧版本保留供审计。"""
    service = AdminRecordService(db)
    return await service.revise_record(record_id, data.content, data.revise_reason, current_user)
