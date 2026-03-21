import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.config import settings
from app.database import get_db
from app.models.base import generate_uuid
from app.models.lab_report import LabReport

router = APIRouter()

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

OCR_PROMPT = (
    "你是一位专业的医疗文档识别助手。请识别并提取这张检验报告单中的所有内容，"
    "包括：报告类型、检验项目名称、检验结果值、参考范围、单位、以及异常标注（如↑↓H L）。"
    "请用结构化文本输出，格式如下：\n"
    "【报告类型】xxx\n"
    "【检验项目】\n"
    "项目名称：值 单位  参考范围  [异常]\n"
    "...\n"
    "如果图片不是检验报告，请简要描述图片内容即可。"
)


async def _ocr_image(content: bytes, mime_type: str) -> Optional[str]:
    """调用 Qwen VL 识别检验报告图片，返回结构化文本"""
    try:
        b64 = base64.b64encode(content).decode()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.aliyun_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.aliyun_api_key}"},
                json={
                    "model": settings.aliyun_model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": OCR_PROMPT},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{mime_type};base64,{b64}"
                            }},
                        ],
                    }],
                    "max_tokens": 1500,
                },
            )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None


@router.post("/upload")
async def upload_lab_report(
    file: UploadFile = File(...),
    encounter_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "仅支持 JPG / PNG / WEBP / PDF 格式")

    content = await file.read()

    # 保存文件
    uploads_root = Path(__file__).resolve().parents[3] / "uploads"
    rel_dir = Path("lab_reports") / (encounter_id or "no_encounter")
    (uploads_root / rel_dir).mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "report").suffix or ".jpg"
    file_name = f"{generate_uuid()}{suffix}"
    rel_path = rel_dir / file_name
    (uploads_root / rel_path).write_bytes(content)

    # 创建数据库记录
    report = LabReport(
        encounter_id=encounter_id,
        doctor_id=current_user.id,
        original_filename=file.filename,
        file_path=str(rel_path),
        mime_type=file.content_type,
        status="analyzing",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # AI OCR（仅图片）
    ocr_text = None
    is_image = file.content_type in {"image/jpeg", "image/png", "image/webp"}
    if is_image:
        ocr_text = await _ocr_image(content, file.content_type)

    report.ocr_text = ocr_text or ("（PDF文件，请手动输入内容）" if not is_image else "（图像识别失败，请手动输入）")
    report.status = "done"
    report.analyzed_at = datetime.now()
    await db.commit()
    await db.refresh(report)

    return {
        "id": report.id,
        "original_filename": report.original_filename,
        "ocr_text": report.ocr_text,
        "status": report.status,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }


@router.get("/")
async def list_lab_reports(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(
        select(LabReport)
        .where(LabReport.encounter_id == encounter_id)
        .order_by(LabReport.created_at.desc())
    )
    reports = result.scalars().all()
    return [
        {
            "id": r.id,
            "original_filename": r.original_filename,
            "ocr_text": r.ocr_text,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]


@router.delete("/{report_id}")
async def delete_lab_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(LabReport).where(LabReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "报告不存在")
    await db.delete(report)
    await db.commit()
    return {"ok": True}
