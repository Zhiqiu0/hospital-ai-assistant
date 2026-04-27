"""
检验报告路由（/api/v1/lab-reports/*）

端点：
  POST   /upload             上传并 OCR（PDF/图片 → 结构化文本）
  GET    /?encounter_id=X    列出某接诊的报告
  DELETE /{report_id}        删除报告（先鉴权）

OCR 业务和 SQL 全在 services/lab_reports_service.py；本文件仅做请求/响应/鉴权。
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.authz import assert_encounter_access
from app.database import get_db
from app.services import lab_reports_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _report_to_dict(r) -> dict:
    return {
        "id": r.id,
        "original_filename": r.original_filename,
        "ocr_text": r.ocr_text,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/upload")
async def upload_lab_report(
    file: UploadFile = File(...),
    encounter_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """上传检验报告（PDF/图片），自动调 OCR。"""
    if file.content_type not in lab_reports_service.ALLOWED_TYPES:
        raise HTTPException(400, "仅支持 JPG / PNG / WEBP / PDF 格式")
    if encounter_id:
        await assert_encounter_access(db, encounter_id, current_user)

    content = await file.read()
    report = await lab_reports_service.process_and_create_report(
        db,
        content=content,
        filename=file.filename,
        mime_type=file.content_type,
        encounter_id=encounter_id,
        doctor_id=current_user.id,
    )
    # 业务里程碑：检验报告上传成功（含 OCR 状态，便于复盘 OCR 失败率）
    logger.info(
        "lab_report.upload: ok report_id=%s encounter_id=%s mime=%s size=%d ocr_status=%s",
        report.id, encounter_id, file.content_type, len(content), report.status,
    )
    return _report_to_dict(report)


@router.get("/")
async def list_lab_reports(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """列出某接诊的所有检验报告。"""
    await assert_encounter_access(db, encounter_id, current_user)
    reports = await lab_reports_service.list_reports(db, encounter_id)
    return [_report_to_dict(r) for r in reports]


@router.delete("/{report_id}")
async def delete_lab_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除检验报告（通过 encounter_id 反查权限）。"""
    report = await lab_reports_service.get_report(db, report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    if report.encounter_id:
        await assert_encounter_access(db, report.encounter_id, current_user)
    await lab_reports_service.delete_report(db, report)
    return {"ok": True}
