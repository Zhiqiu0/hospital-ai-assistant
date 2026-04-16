"""
检验报告路由（/api/v1/lab-reports/*）

支持 PDF / 图片格式的检验报告上传与 OCR 解析：
  - PDF 有文字层 → pdfmupdf 提取 → DeepSeek 文本结构化
  - PDF 扫描件（无文字层）→ 转图片 → Qwen VL OCR
  - 图片 → 直接 Qwen VL OCR
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import base64
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings
from app.core.security import get_current_user
from app.database import get_db
from app.models.base import generate_uuid
from app.models.lab_report import LabReport

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

# 用于结构化解析已提取文字的 prompt（DeepSeek 文本模型）
PARSE_PROMPT = (
    "你是一位专业的医疗检验报告解析助手。以下是从检验报告 PDF 中提取的原始文字内容，"
    "请仔细阅读并整理输出，格式要求如下：\n\n"
    "【报告类型】（如：血常规、生化十六项、甲状腺功能、HPV检测、细菌培养等）\n"
    "【患者信息】姓名：xxx  性别：xxx  年龄：xxx\n"
    "【送检单位】xxx\n"
    "【报告日期】xxx\n"
    "【检验项目】\n"
    "项目名称：结果值 单位  参考范围  [↑异常/↓偏低/正常]\n"
    "（每项一行，如有多项请全部列出）\n"
    "【异常项汇总】（列出所有偏高或偏低的项目及其意义）\n"
    "【诊断/结论】（如报告有文字结论请摘录，无则填【无】）\n\n"
    "注意：如果是培养报告（如细菌培养、血培养、空气培养），请按实际结果描述，"
    "不要强行套表格格式。\n\n"
    "原始文字内容如下：\n"
)

# 用于图片 OCR 的 prompt（Qwen VL 模型）
OCR_PROMPT = (
    "你是一位专业的医疗文档识别助手。请识别并提取这张检验报告单中的所有内容，"
    "包括：报告类型、检验项目名称、检验结果值、参考范围、单位、以及异常标注（如↑↓H L）。\n"
    "请用结构化文本输出，格式如下：\n"
    "【报告类型】xxx\n"
    "【患者信息】姓名：xxx  性别：xxx  年龄：xxx\n"
    "【检验项目】\n"
    "项目名称：结果值 单位  参考范围  [异常标注]\n"
    "...\n"
    "【异常项汇总】（列出所有偏高或偏低的项目）\n"
    "【诊断/结论】（如报告有文字结论请摘录，无则填【无】）\n"
    "如果图片不是检验报告，请简要描述图片内容即可。"
)


def _extract_pdf_text(content: bytes) -> Optional[str]:
    """尝试用 pymupdf 从 PDF 中直接提取文字层，返回原始文本或 None"""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=content, filetype="pdf")
        text = "\n".join(doc[i].get_text() for i in range(len(doc))).strip()
        return text if len(text) > 80 else None
    except Exception as e:
        logger.warning(f"_extract_pdf_text failed: {e}")
        return None


async def _parse_text_with_llm(raw_text: str) -> Optional[str]:
    """将 PDF 提取的原始文字送给 DeepSeek 文本模型进行结构化解析"""
    try:
        prompt = PARSE_PROMPT + raw_text
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.deepseek_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                json={
                    "model": settings.deepseek_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 2000,
                },
            )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"_parse_text_with_llm failed: {e}", exc_info=True)
    return None


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
                    "max_tokens": 2000,
                },
            )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"_ocr_image failed: {e}", exc_info=True)
    return None


async def _ocr_pdf_as_images(content: bytes) -> Optional[str]:
    """PDF 无文字层时，转为图片后调用 Qwen VL 识别（降级方案）"""
    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        results = []
        for i in range(min(len(doc), 3)):  # 最多处理前3页
            pix = doc[i].get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            text = await _ocr_image(img_bytes, "image/png")
            if text:
                results.append(text)
        return "\n\n---\n\n".join(results) if results else None
    except Exception as e:
        logger.error(f"_ocr_pdf_as_images failed: {e}", exc_info=True)
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

    # 保存文件（校验 encounter_id 防路径穿越）
    uploads_root = Path(__file__).resolve().parents[3] / "uploads"
    safe_eid = re.sub(r"[^a-zA-Z0-9_-]", "", encounter_id or "") or "no_encounter"
    rel_dir = Path("lab_reports") / safe_eid
    dest_dir = (uploads_root / rel_dir).resolve()
    if not str(dest_dir).startswith(str(uploads_root.resolve())):
        raise HTTPException(400, "非法路径")
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "report").suffix or ".pdf"
    file_name = f"{generate_uuid()}{suffix}"
    rel_path = rel_dir / file_name
    (dest_dir / file_name).write_bytes(content)

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

    # 解析策略：
    # 1. PDF → 优先直接提取文字层（快、准、省钱）→ DeepSeek 结构化
    # 2. PDF 无文字层 → 转图片 → Qwen VL OCR
    # 3. 图片 → 直接 Qwen VL OCR
    ocr_text = None
    is_pdf = file.content_type == "application/pdf"

    if is_pdf:
        raw_text = _extract_pdf_text(content)
        if raw_text:
            ocr_text = await _parse_text_with_llm(raw_text)
        else:
            # 降级：无文字层 PDF（扫描件），转图片识别
            ocr_text = await _ocr_pdf_as_images(content)
    else:
        # 图片直接 OCR
        ocr_text = await _ocr_image(content, file.content_type)

    report.ocr_text = ocr_text or "（解析失败，请手动输入内容）"
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
