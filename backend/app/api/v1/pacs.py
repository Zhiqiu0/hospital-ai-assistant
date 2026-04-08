# -*- coding: utf-8 -*-
"""
PACS 影像管理 API
- 影像科医生：上传ZIP、选帧、AI分析、审核发布报告
- 临床医生：查看患者影像报告
"""
import os
import subprocess
import zipfile
import shutil
import base64
import io
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import httpx
import numpy as np
import pydicom
from PIL import Image
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import get_current_user
from app.database import get_db
from app.models.imaging import ImagingStudy, ImagingReport
from app.models.encounter import Encounter
from app.config import settings

PRIVILEGED_ROLES = {"radiologist", "admin", "super_admin"}

router = APIRouter()

UPLOADS_DIR = Path(__file__).parent.parent.parent.parent / "uploads" / "pacs"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# 自动抽帧：文件数超过此值才需要选帧
AUTO_ANALYZE_THRESHOLD = 18
# 自动抽帧目标帧数
AUTO_SAMPLE_COUNT = 18


def _dcm_to_jpeg_bytes(dcm_path: str) -> bytes:
    """将单个 DCM 文件转换为 JPEG bytes（含窗宽窗位处理）"""
    ds = pydicom.dcmread(dcm_path)
    arr = ds.pixel_array.astype(np.float32)
    slope = float(getattr(ds, "RescaleSlope", 1))
    intercept = float(getattr(ds, "RescaleIntercept", 0))
    arr = arr * slope + intercept

    if hasattr(ds, "WindowCenter") and hasattr(ds, "WindowWidth"):
        wc = float(ds.WindowCenter[0] if hasattr(ds.WindowCenter, "__iter__") else ds.WindowCenter)
        ww = float(ds.WindowWidth[0] if hasattr(ds.WindowWidth, "__iter__") else ds.WindowWidth)
    else:
        wc = float(np.median(arr))
        ww = float(arr.max() - arr.min()) or 1.0

    lo, hi = wc - ww / 2, wc + ww / 2
    arr = np.clip(arr, lo, hi)
    arr = ((arr - lo) / (hi - lo) * 255).astype(np.uint8)

    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _generate_thumbnails(study_dir: Path, dcm_files: list[str]) -> None:
    """批量生成缩略图，存放在 study_dir/thumbnails/"""
    thumb_dir = study_dir / "thumbnails"
    thumb_dir.mkdir(exist_ok=True)
    for fname in dcm_files:
        thumb_path = thumb_dir / (fname + ".jpg")
        if thumb_path.exists():
            continue
        try:
            jpeg_bytes = _dcm_to_jpeg_bytes(str(study_dir / fname))
            img = Image.open(io.BytesIO(jpeg_bytes))
            img.thumbnail((128, 128))
            img.save(str(thumb_path), "JPEG", quality=70)
        except Exception:
            pass


def _read_dicom_metadata(dcm_path: str) -> dict:
    try:
        ds = pydicom.dcmread(dcm_path, stop_before_pixels=True)
        return {
            "modality": str(getattr(ds, "Modality", "") or ""),
            "body_part": str(getattr(ds, "BodyPartExamined", "") or ""),
            "series_description": str(getattr(ds, "SeriesDescription", "") or ""),
        }
    except Exception:
        return {}


def _smart_sample_frames(dcm_files: list[str], n: int = AUTO_SAMPLE_COUNT) -> list[str]:
    """
    非均匀智能抽帧：头尾各取少量，中间60%区域集中取样。
    适合脊柱/颈椎CT等关键病变集中在中段的序列。

    分配比例（n=18 为例）：
      头部 0-20%  → 3帧
      中部 20-80% → 12帧（密集）
      尾部 80-100%→ 3帧
    """
    total = len(dcm_files)
    if total <= n:
        return dcm_files

    n_edge = max(2, n // 6)       # 头尾各抽约3帧
    n_mid  = n - 2 * n_edge       # 中间约12帧

    mid_start = int(total * 0.20)
    mid_end   = int(total * 0.80)

    # 头部：0 ~ mid_start 均匀取 n_edge 个
    head = [dcm_files[int(mid_start * i / n_edge)] for i in range(n_edge)]

    # 中部：mid_start ~ mid_end 均匀取 n_mid 个（密集）
    mid_span = mid_end - mid_start
    middle = [
        dcm_files[mid_start + int(mid_span * i / (n_mid - 1))]
        for i in range(n_mid)
    ]

    # 尾部：mid_end ~ total-1 均匀取 n_edge 个
    tail_span = (total - 1) - mid_end
    tail = [
        dcm_files[mid_end + int(tail_span * i / max(n_edge - 1, 1))]
        for i in range(n_edge)
    ]

    # 去重、保持顺序
    seen: set[str] = set()
    result: list[str] = []
    for f in head + middle + tail:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result[:n]


# ─── 上传 ZIP ──────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_study(
    background_tasks: BackgroundTasks,
    patient_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """上传 ZIP / RAR 压缩包，后台解压并生成缩略图"""
    fname_lower = file.filename.lower()
    if not (fname_lower.endswith(".zip") or fname_lower.endswith(".rar")):
        raise HTTPException(400, "只支持 ZIP / RAR 格式压缩包")

    is_rar = fname_lower.endswith(".rar")

    # 创建存储目录
    study_id_tmp = str(datetime.now().timestamp()).replace(".", "")
    study_dir = UPLOADS_DIR / study_id_tmp
    study_dir.mkdir(parents=True, exist_ok=True)

    # 保存压缩包
    archive_path = study_dir / ("source.rar" if is_rar else "source.zip")
    content = await file.read()
    archive_path.write_bytes(content)

    # 解压 —— 优先 PATH，再 fallback 常见安装位置
    sevenzip_exe = shutil.which("7z") or shutil.which("7za")
    if not sevenzip_exe:
        _fallback_paths = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            "/usr/bin/7z",
            "/usr/local/bin/7z",
        ]
        sevenzip_exe = next((p for p in _fallback_paths if os.path.exists(p)), None)
    dicom_dir_str = str(study_dir / "dicom")
    try:
        if is_rar:
            if not sevenzip_exe:
                raise Exception("服务器未安装 7-Zip，无法解压 RAR")
            result = subprocess.run(
                [sevenzip_exe, "x", str(archive_path), f"-o{dicom_dir_str}", "-y"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                raise Exception(result.stderr or result.stdout)
        else:
            with zipfile.ZipFile(str(archive_path), "r") as zf:
                zf.extractall(dicom_dir_str)
    except Exception as e:
        shutil.rmtree(str(study_dir), ignore_errors=True)
        raise HTTPException(400, f"解压失败: {e}")

    # 找所有 DCM 文件（递归，用 dict 去重，Windows 大小写不敏感）
    dicom_dir = study_dir / "dicom"
    seen: dict[str, Path] = {}
    for f in dicom_dir.rglob("*"):
        if f.suffix.lower() == ".dcm" and f.is_file():
            seen[f.name.lower()] = f

    # 如果递归找到的文件在子目录，把它们全部移到 dicom 根目录
    for f in seen.values():
        if f.parent != dicom_dir:
            dest = dicom_dir / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
    dcm_files = sorted([f.name for f in dicom_dir.iterdir() if f.suffix.lower() == ".dcm"])

    if not dcm_files:
        shutil.rmtree(str(study_dir), ignore_errors=True)
        raise HTTPException(400, "压缩包中未找到 DCM 文件")

    # 读取第一个文件的元数据
    meta = _read_dicom_metadata(str(dicom_dir / dcm_files[0]))

    # 写入数据库
    study = ImagingStudy(
        patient_id=patient_id,
        uploaded_by=current_user.id,
        modality=meta.get("modality") or None,
        body_part=meta.get("body_part") or None,
        series_description=meta.get("series_description") or None,
        total_frames=len(dcm_files),
        storage_dir=str(dicom_dir),
        status="pending",
    )
    db.add(study)
    await db.commit()
    await db.refresh(study)

    # 后台生成缩略图
    background_tasks.add_task(_generate_thumbnails, dicom_dir, dcm_files)

    return {
        "study_id": study.id,
        "total_frames": len(dcm_files),
        "modality": meta.get("modality"),
        "body_part": meta.get("body_part"),
        "auto_select": len(dcm_files) <= AUTO_ANALYZE_THRESHOLD,
    }


# ─── 获取切片列表 ───────────────────────────────────────────────────────────

@router.get("/{study_id}/frames")
async def get_frames(
    study_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """返回所有切片文件名列表 + 自动抽帧建议"""
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")

    dicom_dir = Path(study.storage_dir)
    dcm_files = sorted(list({f.name for f in dicom_dir.glob("*.DCM")} | {f.name for f in dicom_dir.glob("*.dcm")}))

    # 自动抽帧建议（智能非均匀采样）
    if len(dcm_files) <= AUTO_ANALYZE_THRESHOLD:
        suggested = dcm_files
    else:
        suggested = _smart_sample_frames(dcm_files, AUTO_SAMPLE_COUNT)

    return {
        "study_id": study_id,
        "total": len(dcm_files),
        "frames": dcm_files,
        "suggested": suggested,
    }


# ─── 缩略图服务 ─────────────────────────────────────────────────────────────

@router.get("/{study_id}/thumbnail/{filename}")
async def get_thumbnail(
    study_id: str,
    filename: str,
    wc: Optional[float] = None,
    ww: Optional[float] = None,
    db: AsyncSession = Depends(get_db),
):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "非法文件名")
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")

    dicom_dir = Path(study.storage_dir)
    dcm_path = dicom_dir / filename

    # 自定义窗位窗宽时，实时渲染，不使用缓存缩略图
    if wc is not None and ww is not None:
        if not dcm_path.exists():
            raise HTTPException(404, "文件不存在")
        try:
            ds = pydicom.dcmread(str(dcm_path))
            arr = ds.pixel_array.astype(np.float32)
            slope = float(getattr(ds, "RescaleSlope", 1))
            intercept = float(getattr(ds, "RescaleIntercept", 0))
            arr = arr * slope + intercept
            lo, hi = wc - ww / 2, wc + ww / 2
            arr = np.clip(arr, lo, hi)
            arr = ((arr - lo) / (hi - lo) * 255).astype(np.uint8)
            img = Image.fromarray(arr)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            from fastapi.responses import Response
            return Response(content=buf.getvalue(), media_type="image/jpeg")
        except Exception as e:
            raise HTTPException(500, f"渲染失败: {e}")

    thumb_path = dicom_dir / "thumbnails" / (filename + ".jpg")

    # 如果缩略图还没生成，实时生成
    if not thumb_path.exists():
        if not dcm_path.exists():
            raise HTTPException(404, "文件不存在")
        try:
            jpeg_bytes = _dcm_to_jpeg_bytes(str(dcm_path))
            img = Image.open(io.BytesIO(jpeg_bytes))
            img.thumbnail((128, 128))
            thumb_path.parent.mkdir(exist_ok=True)
            img.save(str(thumb_path), "JPEG", quality=70)
        except Exception as e:
            raise HTTPException(500, f"缩略图生成失败: {e}")

    return FileResponse(str(thumb_path), media_type="image/jpeg")


# ─── 原始 DCM 文件服务（供 Cornerstone.js 加载）──────────────────────────────

@router.get("/{study_id}/dicom/{filename}")
async def get_dicom_file(
    study_id: str,
    filename: str,
    db: AsyncSession = Depends(get_db),
):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "非法文件名")
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")

    dcm_path = Path(study.storage_dir) / filename
    if not dcm_path.exists():
        raise HTTPException(404, "文件不存在")

    return FileResponse(str(dcm_path), media_type="application/dicom")


# ─── AI 分析 ────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    selected_frames: List[str]


@router.post("/{study_id}/analyze")
async def analyze_study(
    study_id: str,
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """将选中帧发给千问 AI 分析，返回结构化报告"""
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")

    dicom_dir = Path(study.storage_dir)
    selected = body.selected_frames[:20]  # 最多20帧（建议18帧）

    # 转换为 JPEG base64
    images_content = []
    for fname in selected:
        dcm_path = dicom_dir / fname
        if not dcm_path.exists():
            continue
        try:
            jpeg_bytes = _dcm_to_jpeg_bytes(str(dcm_path))
            b64 = base64.b64encode(jpeg_bytes).decode()
            images_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
            })
        except Exception:
            continue

    if not images_content:
        raise HTTPException(400, "没有可分析的影像帧")

    modality = study.modality or "影像"
    body_part = study.body_part or ""

    prompt = f"""你是一位经验丰富的放射科医生。请对以下{modality}影像（{body_part}）进行专业分析。

请按以下结构输出报告：

【影像类型】
（说明检查类型、部位、序列）

【影像所见】
（逐系统描述主要所见，使用规范医学术语）

【印象】
（总结主要发现，按重要性排列）

【建议】
（后续处理或随访建议）

要求：使用规范中文医学术语，客观描述所见，不过度推断。"""

    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}] + images_content}]

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.aliyun_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.aliyun_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.aliyun_model,
                    "messages": messages,
                    "max_tokens": 1000,
                },
            )
            if resp.status_code != 200:
                raise HTTPException(500, f"AI 分析失败: {resp.text}")
            ai_result = resp.json()["choices"][0]["message"]["content"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"AI 服务异常: {e}")

    # 保存到数据库
    report = await db.get(ImagingReport, study_id)
    if not report:
        # 查找是否已有 report
        result = await db.execute(select(ImagingReport).where(ImagingReport.study_id == study_id))
        report = result.scalar_one_or_none()

    if report:
        report.selected_frames = selected
        report.ai_analysis = ai_result
        report.final_report = ai_result
    else:
        report = ImagingReport(
            study_id=study_id,
            radiologist_id=current_user.id,
            selected_frames=selected,
            ai_analysis=ai_result,
            final_report=ai_result,
        )
        db.add(report)

    study.status = "analyzed"
    await db.commit()

    return {"ai_analysis": ai_result}


# ─── 保存 & 发布报告 ─────────────────────────────────────────────────────────

class PublishRequest(BaseModel):
    final_report: str


@router.put("/{study_id}/report")
async def save_report(
    study_id: str,
    body: PublishRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(ImagingReport).where(ImagingReport.study_id == study_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "报告不存在，请先进行 AI 分析")

    report.final_report = body.final_report
    await db.commit()
    return {"ok": True}


@router.post("/{study_id}/publish")
async def publish_report(
    study_id: str,
    body: PublishRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(ImagingReport).where(ImagingReport.study_id == study_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "报告不存在，请先进行 AI 分析")

    report.final_report = body.final_report
    report.is_published = True
    report.published_at = datetime.utcnow()
    report.radiologist_id = current_user.id

    study = await db.get(ImagingStudy, study_id)
    if study:
        study.status = "published"

    await db.commit()
    return {"ok": True, "published_at": report.published_at.isoformat()}


# ─── 获取患者的已发布报告（临床医生用）────────────────────────────────────────

@router.get("/patient/{patient_id}/reports")
async def get_patient_reports(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 普通医生只能访问自己有 encounter 的患者
    if getattr(current_user, "role", "doctor") not in PRIVILEGED_ROLES:
        enc = await db.execute(
            select(Encounter.id).where(
                Encounter.patient_id == patient_id,
                Encounter.doctor_id == current_user.id,
            ).limit(1)
        )
        if not enc.scalar_one_or_none():
            raise HTTPException(403, "无权访问该患者影像资料")

    result = await db.execute(
        select(ImagingStudy, ImagingReport)
        .join(ImagingReport, ImagingReport.study_id == ImagingStudy.id, isouter=True)
        .where(ImagingStudy.patient_id == patient_id)
        .where(ImagingStudy.status == "published")
        .order_by(ImagingStudy.created_at.desc())
    )
    rows = result.all()
    return [
        {
            "study_id": s.id,
            "modality": s.modality,
            "body_part": s.body_part,
            "series_description": s.series_description,
            "total_frames": s.total_frames,
            "created_at": s.created_at.isoformat(),
            "final_report": r.final_report if r else None,
            "published_at": r.published_at.isoformat() if r and r.published_at else None,
        }
        for s, r in rows
    ]


# ─── 临床医生：直接上传 JPG/PNG 分析 ────────────────────────────────────────

@router.post("/analyze-image")
async def analyze_image(
    file: UploadFile = File(...),
    image_type: str = Form(default=""),
    current_user=Depends(get_current_user),
):
    """临床医生上传 JPG/PNG/DCM，直接送千问分析，返回结构化报告"""
    allowed_img = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = file.content_type or ""
    filename = file.filename or ""
    is_dcm = filename.lower().endswith(".dcm") or content_type in {"application/dicom", "application/octet-stream"}

    if not is_dcm and content_type not in allowed_img and not any(filename.lower().endswith(e) for e in [".jpg", ".jpeg", ".png", ".webp"]):
        raise HTTPException(400, "请上传 JPG/PNG/WebP 或 DCM 格式文件")

    raw_bytes = await file.read()

    if is_dcm:
        # DCM → JPEG（含窗宽窗位处理）
        try:
            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = tmp.name
            img_bytes = _dcm_to_jpeg_bytes(tmp_path)
            os.unlink(tmp_path)
        except Exception as e:
            raise HTTPException(400, f"DCM 文件解析失败: {e}")
        mime = "image/jpeg"
    else:
        img_bytes = raw_bytes
        mime = content_type if content_type in allowed_img else "image/jpeg"

    b64 = base64.b64encode(img_bytes).decode()

    hint = f"（{image_type}）" if image_type else ""
    prompt = f"""你是一位经验丰富的放射科医生。请对以下医学影像{hint}进行专业分析。

请按以下结构输出报告：

【影像类型】
（说明检查类型、部位）

【影像所见】
（逐系统描述主要所见，使用规范医学术语）

【印象】
（总结主要发现，按重要性排列）

【建议】
（后续处理或随访建议）

要求：使用规范中文医学术语，客观描述所见，不过度推断。"""

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.aliyun_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.aliyun_api_key}", "Content-Type": "application/json"},
                json={
                    "model": settings.aliyun_model,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ]}],
                    "max_tokens": 800,
                },
            )
            if resp.status_code != 200:
                raise HTTPException(500, f"AI 分析失败: {resp.text}")
            return {"analysis": resp.json()["choices"][0]["message"]["content"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"AI 服务异常: {e}")


# ─── 获取影像科工作列表 ──────────────────────────────────────────────────────

@router.get("/studies")
async def list_studies(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 只有放射科医生和管理员可查看全部影像列表
    if getattr(current_user, "role", "doctor") not in PRIVILEGED_ROLES:
        raise HTTPException(403, "仅放射科医生可访问影像列表")

    q = select(ImagingStudy).order_by(ImagingStudy.created_at.desc())
    if status:
        q = q.where(ImagingStudy.status == status)
    result = await db.execute(q)
    studies = result.scalars().all()
    return [
        {
            "study_id": s.id,
            "patient_id": s.patient_id,
            "modality": s.modality,
            "body_part": s.body_part,
            "series_description": s.series_description,
            "total_frames": s.total_frames,
            "status": s.status,
            "created_at": s.created_at.isoformat(),
        }
        for s in studies
    ]
