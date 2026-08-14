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
from app.core.storage_paths import UPLOADS_ROOT, resolve_upload_path
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
    # 用单一真源而不是自己数 parents 层数（2026-08-14 第八轮审计修复）：
    # 本文件在 app/services/ 下只有三层，原先照抄了 app/api/v1/ 下四层文件的
    # parents[3]，算出来是仓库根而非 backend/——容器里就落到了挂载卷之外，
    # 每次 deploy 清零且从未被备份过，而路径穿越校验用的也是这个错误 root
    # 所以自洽通过、不报任何错。详见 app/core/storage_paths.py。
    uploads_root = UPLOADS_ROOT
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


# 卡在 analyzing 多久就认定是被中断的（秒）。OCR 最长约 180s（PDF 扫描件
# 最多 3 页 × 60s 超时），留一倍余量。
_ANALYZING_STALE_SECONDS = 360


async def reclaim_stale_analyzing(db: AsyncSession) -> int:
    """把卡死在 analyzing 的报告标记为失败，返回处理条数。

    2026-08-14 第八轮审计修复：process_and_create_report 是「先落 analyzing →
    再做最长 3 分钟的外部调用 → 最后落 done」。只要在这段窗口里进程结束——
    **部署重启（本项目每次 deploy 必然发生）**、容器 OOM、compose 重建——
    第二次 commit 永远不会执行，该记录永久停在 analyzing 且 ocr_text 为 NULL。
    原先全仓没有任何针对 analyzing 的扫描/重试/超时兜底，前端也不渲染 status，
    医生看到的是一张内容为空、类型「未知类型」的卡片：既不知道它失败了，
    也没法让它重来，只能重新上传，旧记录变成死数据留在患者名下。
    注意正常失败路径是有兜底文案的（"（解析失败，请手动输入内容）"），
    唯独被中断这条路径什么都没有——这里补上，让它和正常失败长得一样。
    """
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(seconds=_ANALYZING_STALE_SECONDS)
    stale = (await db.execute(
        select(LabReport).where(
            LabReport.status == "analyzing",
            LabReport.created_at < cutoff,
        )
    )).scalars().all()
    for report in stale:
        report.ocr_text = report.ocr_text or "（解析被中断，请手动输入内容或重新上传）"
        report.status = "done"
        report.analyzed_at = datetime.now()
    if stale:
        await db.commit()
        logger.warning("lab_report.reclaim: 回收卡死的解析任务 %d 条", len(stale))
    return len(stale)


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
    """删除检验报告，**连同磁盘上的原图一起删**。

    2026-08-14 第八轮审计修复：原先只 db.delete(report)。而 file_path 列是
    全系统指向那个文件的**唯一引用**，行一删就再没有任何程序能定位到它——
    既不会被清理，也无法被找出来人工删除。那张图上有患者姓名、性别、年龄和
    全部检验结果。医生上传错了病人的化验单点删除，界面上消失了，
    服务器上一份不少。
    对照：语音记录删除（ai_voice_records）会先 unlink 音频再删行，
    还有 cleanup_voice.py + 每日 cron 做 30 天保留期清理；检验报告两样都没有。

    先删文件再删行：反过来的话文件删失败就再也找不到它了。
    文件删不掉不阻断删行——那样会让医生连"删掉错误报告"都做不到。
    """
    if report.file_path:
        try:
            path = resolve_upload_path(report.file_path)
            if path.exists():
                path.unlink()
        except (ValueError, OSError) as exc:
            # 越界路径/权限问题：记下来人工清，不挡住删除本身
            logger.warning(
                "lab_report.delete: 原图删除失败 report_id=%s path=%s err=%s",
                report.id, report.file_path, exc,
            )
    await db.delete(report)
    await db.commit()
