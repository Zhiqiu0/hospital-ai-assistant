# -*- coding: utf-8 -*-
"""
PACS 上传子路由（POST /upload）

从 pacs.py 拆出（Round 6 瘦身）：只负责压缩包上传 → 解压 → STOW 到 Orthanc →
写 ImagingStudy 索引。行为与拆分前逐字一致，路由路径/方法/依赖零改动。
本模块自建 router，由 pacs.py 的主 router.include_router() 拼回。
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
import asyncio
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.core.authz import assert_pacs_write
from app.core.upload_limits import MAX_DICOM_BYTES, read_upload_capped
from app.database import get_db
from app.services.orthanc_client import orthanc_client
# Round 5/6：PACS 业务逻辑服务包（解压/帧查询/渲染缓存/报告 ORM）
from app.services.pacs import dicom_service, frame_service, render_cache, report_service
from app.services.pacs.dicom_service import AUTO_ANALYZE_THRESHOLD

router = APIRouter()

# 临时解压目录：仅在 upload 期间存在，STOW 到 Orthanc 后立刻清理
# 不再像 R1 之前那样长期持有 DICOM 文件
TEMP_UPLOAD_DIR = Path(tempfile.gettempdir()) / "mediscribe_pacs_upload"
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ─── 上传 ZIP/RAR → STOW 到 Orthanc ────────────────────────────────────────


@router.post("/upload")
async def upload_study(
    patient_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """上传 ZIP/RAR 压缩包 → 解压 → STOW 到 Orthanc → 写 ImagingStudy 索引。

    R1 迁移要点：
      - 不再持久化 DICOM 文件到本地（uploads/pacs 目录），所有文件直接 STOW
        到 Orthanc，本地只在 STOW 完成前的临时目录里短暂存在
      - ImagingStudy.storage_dir 不再写入（保留 NULL，向后兼容旧数据）
      - 新增 study_instance_uid 字段：从 STOW 响应里抽出 DICOM 标准 UID，
        后续所有 Orthanc 调用都用它索引
    """
    # 只允许影像科医生 + 管理员上传；临床医生看影像走只读路径
    assert_pacs_write(current_user)
    archive_kind = dicom_service.detect_archive_kind(file.filename or "")
    if not archive_kind:
        raise HTTPException(
            400,
            "不支持的压缩格式，请使用：ZIP / RAR / 7Z / TAR / TAR.GZ / TGZ / "
            "TAR.BZ2 / TBZ / TAR.XZ / ISO 之一",
        )

    # 临时工作目录：STOW 完成或异常后立即清理
    work_dir = TEMP_UPLOAD_DIR / f"upload_{datetime.now().timestamp():.6f}".replace(".", "")
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1-3) 落盘压缩包 → 解压 → 扫描 .dcm 路径（不读字节，已下沉 dicom_service）
        # 分块读 + 超 100MB 即 413，避免超大压缩包吃满内存
        archive_bytes = await read_upload_capped(file, MAX_DICOM_BYTES)
        dcm_paths = dicom_service.extract_and_scan_dcm(archive_bytes, work_dir, archive_kind)
        if not dcm_paths:
            raise HTTPException(400, "压缩包中未找到 DCM 文件")

        # 3.5) ⚡ 幂等快路径：只读第一个 DCM 的 metadata 拿 StudyInstanceUID 查 DB
        #      命中已存在 → 立即返回原 study_id，不读其他文件、不上传 Orthanc
        #      重传 537 帧 study 从分钟级降到亚秒级（查重已下沉 report_service）
        preflight_study_uid = dicom_service.read_preflight_study_uid(dcm_paths[0])
        if preflight_study_uid:
            dup = await report_service.find_duplicate_study(db, preflight_study_uid, patient_id)
            if dup:
                return dup

        # 3.6) 不重复 → 读所有文件字节 + pydicom 解析每个 SOPInstanceUID/SeriesInstanceUID/InstanceNumber
        # （仅 metadata 不读 pixel，单张 ~5ms；frames_meta 用于 /frames 端点的
        # Redis 缓存，避免实时查 Orthanc QIDO 慢 5-10s；已按 instance_number 排序）
        dicom_bytes_list, instance_uids, frames_meta = dicom_service.parse_dicom_files(dcm_paths)
        if not dicom_bytes_list:
            raise HTTPException(400, "DCM 文件读取失败")

        # 4) ⚡ 并行：STOW 到 Orthanc + pydicom 本地渲染 256/1024 JPEG → Redis
        # 优化 3 核心：backend 渲染每张 ~3ms × 537 / 8 路 ≈ 0.2s
        # STOW 单 instance 并发 8 路 ≈ 5-15s（Orthanc 写盘 + 索引）
        # 用 asyncio.gather 同时跑，总时间 = max(两者) ≈ STOW 时间，渲染白送
        target_study_uid = preflight_study_uid
        instances_for_render = list(zip(instance_uids, dicom_bytes_list))

        async def _do_stow():
            return await orthanc_client.stow_instances(dicom_bytes_list)

        async def _do_render():
            if target_study_uid:
                await render_cache.render_and_cache_all(target_study_uid, instances_for_render)

        stow_resp, _ = await asyncio.gather(_do_stow(), _do_render())

        # 5) 从 STOW 响应取 StudyInstanceUID（preflight 拿到的优先）
        study_uid = target_study_uid or frame_service.extract_study_uid_from_stow_response(stow_resp)
        if not study_uid:
            raise HTTPException(500, "Orthanc 上传成功但未返回 StudyInstanceUID")

        # 5.5) 把 frames_meta 存到 Redis，让 /frames 端点免去实时查 Orthanc QIDO
        await render_cache.cache_frames_meta(study_uid, frames_meta)

        # 6) 幂等性兜底（preflight 读不到 UID 时由 STOW 响应再查一次）
        dup = await report_service.find_duplicate_study(db, study_uid, patient_id)
        if dup:
            return dup

        # 7) 取 study 元数据（modality / body_part / series_description / 实例总数）
        meta = await frame_service.fetch_study_metadata(study_uid)

        # 8) 写业务表 ImagingStudy（已下沉 report_service）
        # 注：上面 asyncio.gather 已经把所有 instance 的缩略图 + 高清预览
        # 用 pydicom 本地渲染并写入 Redis 完毕。此处不再额外预热。
        study = await report_service.create_imaging_study(
            db, patient_id, current_user.id, study_uid, meta
        )

        return {
            "study_id": study.id,
            "study_instance_uid": study_uid,
            "total_frames": meta.get("total_instances", 0),
            "modality": meta.get("modality"),
            "body_part": meta.get("body_part"),
            "auto_select": meta.get("total_instances", 0) <= AUTO_ANALYZE_THRESHOLD,
            "duplicate": False,
        }
    finally:
        # 无论成功失败都清理临时目录
        shutil.rmtree(str(work_dir), ignore_errors=True)
