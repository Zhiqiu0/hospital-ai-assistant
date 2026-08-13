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


@router.get("/signature-integrity")
async def verify_signature_integrity(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """校验全部已签发病历的电子签名哈希链完整性（2026-08-11 病历可信）。

    **补上链接校验**（2026-08-13 第五轮审计修复）：原先只是对每个版本做单行
    自校验——把该行自己存的 prev_hash 当哈希输入重算一遍，从不比对它是否真等于
    前一环的 sign_hash。那样"链"形同虚设：删掉中间版本、或改完正文按同一
    prev_hash 重算 sign_hash（算法无密钥且就在仓库里），都能全身而退，
    而端点照样返回"全部通过"——这正是评审现场最不能出的错。
    现在 verify_chain 逐环比对链接 + 逐行自校验，两类篡改都能报出来。

    返回：{"total": 校验总数, "verified": 通过数, "tampered": [异常明细]}
    """
    from sqlalchemy import func, select

    from app.models.medical_record import RecordVersion
    from app.services._record_signature import verify_chain

    total = (await db.execute(
        select(func.count()).select_from(RecordVersion)
        .where(RecordVersion.sign_hash.isnot(None))
    )).scalar() or 0

    tampered = await verify_chain(db)
    bad = {(t["medical_record_id"], t["version_no"]) for t in tampered}
    return {
        "total": total,
        "verified": total - len(bad),
        "tampered": tampered,
        "ok": len(tampered) == 0,
    }
