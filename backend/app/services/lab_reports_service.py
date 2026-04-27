"""
检验报告业务服务（services/lab_reports_service.py）

抽自 api/v1/lab_reports.py。职责：
  - OCR 策略分派（PDF 文字层 / PDF 扫描件 / 图片）
  - 调外部 LLM（DeepSeek 文本 + Qwen VL 视觉）
  - 文件落盘（路径穿越校验）
  - LabReport ORM CRUD

路由层不再碰 SQL / httpx / 文件系统，只负责解析请求、鉴权、组装响应。
"""

import base64
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.base import generate_uuid
from app.models.lab_report import LabReport


logger = logging.getLogger(__name__)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

# 结构化解析 PDF 文字层的 prompt（DeepSeek）
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

# 图片 OCR 的 prompt（Qwen VL）
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


# ── 内部：OCR 策略实现 ─────────────────────────────────────────────────────────

def _extract_pdf_text(content: bytes) -> Optional[str]:
    """尝试用 pymupdf 从 PDF 提取文字层；文字过短视为扫描件，返回 None。"""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=content, filetype="pdf")
        text = "\n".join(doc[i].get_text() for i in range(len(doc))).strip()
        return text if len(text) > 80 else None
    except Exception as exc:
        # 用 %s 占位符让 Sentry 能按"消息模板"聚合同类错误
        # （f-string 在调用前已格式化，每条 message 都不一样，无法分组）
        logger.warning("lab_reports.pdf_extract: failed err=%s", exc)
        return None


async def _parse_text_with_llm(raw_text: str) -> Optional[str]:
    """送 DeepSeek 文本模型结构化 PDF 提取的文字。"""
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
    except Exception as exc:
        # logger.exception 自带堆栈采集，比 error+exc_info=True 更简洁
        logger.exception("lab_reports.parse_llm: failed err=%s", exc)
    return None


async def _ocr_image(content: bytes, mime_type: str) -> Optional[str]:
    """Qwen VL 识别单张图片。"""
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
    except Exception as exc:
        logger.exception("lab_reports.ocr_image: failed err=%s", exc)
    return None


async def _ocr_pdf_as_images(content: bytes) -> Optional[str]:
    """PDF 无文字层时转图片 OCR（最多前 3 页）。"""
    try:
        import fitz
        doc = fitz.open(stream=content, filetype="pdf")
        results = []
        for i in range(min(len(doc), 3)):
            pix = doc[i].get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            text = await _ocr_image(img_bytes, "image/png")
            if text:
                results.append(text)
        return "\n\n---\n\n".join(results) if results else None
    except Exception as exc:
        logger.exception("lab_reports.ocr_pdf: failed err=%s", exc)
        return None


# ── 对外 API ──────────────────────────────────────────────────────────────────

def save_report_file(content: bytes, filename: Optional[str], encounter_id: Optional[str]) -> Path:
    """把文件落盘到 uploads/lab_reports/<encounter_id>/<uuid>.<ext>。

    encounter_id 清洗为安全目录名，dest_dir 必须在 uploads/ 之下（防路径穿越）。
    返回相对 uploads_root 的路径（供 DB 存 file_path）。
    """
    uploads_root = Path(__file__).resolve().parents[3] / "uploads"
    safe_eid = re.sub(r"[^a-zA-Z0-9_-]", "", encounter_id or "") or "no_encounter"
    rel_dir = Path("lab_reports") / safe_eid
    dest_dir = (uploads_root / rel_dir).resolve()
    if not str(dest_dir).startswith(str(uploads_root.resolve())):
        raise HTTPException(400, "非法路径")
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(filename or "report").suffix or ".pdf"
    file_name = f"{generate_uuid()}{suffix}"
    rel_path = rel_dir / file_name
    (dest_dir / file_name).write_bytes(content)
    return rel_path


async def process_and_create_report(
    db: AsyncSession,
    *,
    content: bytes,
    filename: Optional[str],
    mime_type: str,
    encounter_id: Optional[str],
    doctor_id: str,
) -> LabReport:
    """完整处理流程：落盘 → 创建 DB 记录 → OCR → 更新 ocr_text 与 status。"""
    rel_path = save_report_file(content, filename, encounter_id)

    report = LabReport(
        encounter_id=encounter_id,
        doctor_id=doctor_id,
        original_filename=filename,
        file_path=str(rel_path),
        mime_type=mime_type,
        status="analyzing",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # OCR 策略分派：PDF 文字层 → DeepSeek；PDF 扫描件 / 图片 → Qwen VL
    ocr_text: Optional[str] = None
    if mime_type == "application/pdf":
        raw_text = _extract_pdf_text(content)
        if raw_text:
            ocr_text = await _parse_text_with_llm(raw_text)
        else:
            ocr_text = await _ocr_pdf_as_images(content)
    else:
        ocr_text = await _ocr_image(content, mime_type)

    report.ocr_text = ocr_text or "（解析失败，请手动输入内容）"
    report.status = "done"
    report.analyzed_at = datetime.now()
    await db.commit()
    await db.refresh(report)
    return report


async def list_reports(db: AsyncSession, encounter_id: str) -> list[LabReport]:
    stmt = (
        select(LabReport)
        .where(LabReport.encounter_id == encounter_id)
        .order_by(LabReport.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_report(db: AsyncSession, report_id: str) -> Optional[LabReport]:
    result = await db.execute(select(LabReport).where(LabReport.id == report_id))
    return result.scalar_one_or_none()


async def delete_report(db: AsyncSession, report: LabReport) -> None:
    await db.delete(report)
    await db.commit()
