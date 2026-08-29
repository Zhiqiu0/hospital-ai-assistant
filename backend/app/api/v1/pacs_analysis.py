# -*- coding: utf-8 -*-
"""
PACS AI 分析子路由（POST /{study_id}/analyze、POST /analyze-image）

从 pacs.py 拆出（Round 6 瘦身）：负责从 Orthanc 拉关键帧 → 千问 VL 分析，
以及临床医生单张 JPG/PNG/DCM 直接分析（不入库）。行为逐字一致，依赖零改动。
本模块自建 router，由 pacs.py 的主 router.include_router() 拼回。
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
from typing import List

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel


# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.core.authz import assert_pacs_write
from app.core.upload_limits import MAX_DICOM_BYTES, read_upload_capped
from app.database import AsyncSessionLocal
from app.models.imaging import ImagingStudy
from app.services.ai.prompts_pacs import build_study_prompt, build_image_prompt
# Round 5/6：PACS 业务逻辑服务包（AI 分析/帧查询/报告 ORM）
from app.services.pacs import analysis_service, frame_service, report_service

router = APIRouter()


# ─── AI 分析（从 Orthanc 拉关键帧 → 千问 VL；调用逻辑搬至 analysis_service）──

class AnalyzeRequest(BaseModel):
    """前端传选中的 instance UID 列表（R1 后不再用文件名）。"""
    selected_frames: List[str]


@router.post("/{study_id}/analyze")
async def analyze_study(
    study_id: str,
    body: AnalyzeRequest,
    current_user=Depends(get_current_user),
):
    """从 Orthanc 拉选中帧 → 千问 VL 分析 → 写报告。


    R1 改造：
      - 选中帧由 instance UID 标识（不再是文件名）
      - 帧数上限按 modality 自适应（CT/MR 18、X 光 4、超声 6 等）
      - 帧像素从 Orthanc WADO render 拉（已 JPEG 编码，省一次本地转码）

    连接持有（2026-08-14 第七轮审计修复）：
      本端点原先用 Depends(get_db)，也就是**整个请求周期独占一条池连接**——
      包括从 Orthanc 拉 18 帧 CT 和最长 120 秒的千问 VL 调用。连接池是
      pool_size=10 + max_overflow=20，几位放射科医生同时点分析，就有一批
      连接被扣住两分钟不干活，其它所有接口（含医生写病历）跟着排队等连接。
      现在拆成两段短事务，中间那段长外部调用**不持有任何连接**。
    """
    assert_pacs_write(current_user)

    # ── 短事务 1：只取分析需要的字段，取完立刻归还连接 ──────────────────────
    async with AsyncSessionLocal() as db:
        study = await db.get(ImagingStudy, study_id)
        if not study:
            raise HTTPException(404, "检查不存在")
        if not study.study_instance_uid:
            raise HTTPException(410, "该检查为旧版本数据，已不支持分析")
        # 拷成普通值：出了 with 之后 ORM 实例就 detach 了，不能再碰它的属性
        study_uid = study.study_instance_uid
        modality = study.modality
        body_part = study.body_part

    cap = analysis_service.frame_cap_for(modality)
    selected = body.selected_frames[:cap]
    if not selected:
        raise HTTPException(400, "未选中任何影像帧")

    # ── 长外部调用段：不持有数据库连接 ─────────────────────────────────────
    # 从 Orthanc 拉选中帧 JPEG（series 反向索引 + WADO render，搬至 analysis_service）
    images = await analysis_service.fetch_frames_for_analysis(study_uid, selected)
    if not images:
        raise HTTPException(400, "没有可分析的影像帧")

    # 构建 prompt + 调千问 VL（统一走 call_qwen_vl，与单图分析共用代码路径）
    prompt = build_study_prompt(modality, body_part)
    ai_result = await analysis_service.call_qwen_vl(prompt, images, max_tokens=1000)

    # ── 短事务 2：写回报告 ─────────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        # 重新取一次：上一段可能过了两分钟，检查有可能已被删除
        study = await db.get(ImagingStudy, study_id)
        if not study:
            raise HTTPException(410, "检查已被删除，分析结果无法保存")
        # unique 约束保证一个 study 至多一条 report（搬至 report_service）
        await report_service.upsert_analysis_report(
            db, study, study_id, selected, ai_result, current_user.id
        )

    return {"ai_analysis": ai_result}


# ─── 临床医生：直接上传 JPG/PNG 分析 ────────────────────────────────────────

@router.post("/analyze-image")
async def analyze_image(
    file: UploadFile = File(...),
    image_type: str = Form(default=""),
    current_user=Depends(get_current_user),
):
    """临床医生上传 JPG/PNG/DCM，直接送千问分析，返回结构化报告"""
    # AI 影像分析角色门槛（2026-08-29 第七轮渗透审计）：付费千问 VL 通道，
    # 临床医生/影像医师/管理角色可用，只读角色（qc_officer/nurse）不可
    from app.core.authz import RECORD_WRITE_ROLES
    _allowed = RECORD_WRITE_ROLES | {"radiologist"}
    if getattr(current_user, "role", None) not in _allowed:
        raise HTTPException(403, "当前角色无影像 AI 分析权限")
    allowed_img = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = file.content_type or ""
    filename = file.filename or ""
    is_dcm = filename.lower().endswith(".dcm") or content_type in {"application/dicom", "application/octet-stream"}

    if not is_dcm and content_type not in allowed_img and not any(filename.lower().endswith(e) for e in [".jpg", ".jpeg", ".png", ".webp"]):
        raise HTTPException(400, "请上传 JPG/PNG/WebP 或 DCM 格式文件")

    # 分块读 + 超 100MB 即 413（单张 DCM/图片，复用 DICOM 上限）
    raw_bytes = await read_upload_capped(file, MAX_DICOM_BYTES)

    if is_dcm:
        # DCM → JPEG：临时 STOW 到 Orthanc → WADO render 拿 JPEG → 删除临时 study
        # （"分析完即删"模式不污染 Orthanc 索引，已下沉 frame_service）
        img_bytes = await frame_service.dcm_to_jpeg_via_orthanc(raw_bytes)
        mime = "image/jpeg"
    else:
        img_bytes = raw_bytes
        mime = content_type if content_type in allowed_img else "image/jpeg"

    # 构建 prompt + 调千问 VL（与 analyze_study 共用 analysis_service.call_qwen_vl）
    prompt = build_image_prompt(image_type)
    analysis = await analysis_service.call_qwen_vl(prompt, [(img_bytes, mime)], max_tokens=800)
    return {"analysis": analysis}
