# -*- coding: utf-8 -*-
"""
PACS 影像管理路由（/api/v1/pacs/*）

R1 迁移后职责变化：
  本模块不再持有任何本地 DICOM 解析/渲染代码，所有 DICOM 操作（存储/查询/
  缩略图渲染/原图返回）全部委托给 Orthanc DICOM 服务器（DICOMweb 标准协议）。
  本模块只负责：上传适配、鉴权、AI 调用编排、报告流程、与业务表 ImagingStudy/
  ImagingReport 的关联维护。

端点列表：
  POST /upload                    上传 DICOM ZIP/RAR，解压后 STOW 到 Orthanc
  GET  /{study_id}/frames         返回该 study 的 instance UID 列表 + 智能抽帧建议
  GET  /{study_id}/thumbnail/{i}  通过 WADO 渲染缩略图（支持自定义窗宽窗位）
  GET  /{study_id}/dicom/{i}      通过 WADO 返回原始 DCM 文件（供前端 viewer 加载）
  POST /{study_id}/analyze        从 Orthanc 拉关键帧 → 千问 VL 分析
  PUT  /{study_id}/report         保存（草稿）影像报告
  POST /{study_id}/publish        发布影像报告（正式签发）
  GET  /patient/{patient_id}/reports  获取患者已发布的影像报告列表
  POST /analyze-image             临床医生上传单张 JPG/PNG 直接分析（不入库）
  GET  /studies                   影像科工作列表

权限分层：
  普通医生（doctor）: 只能访问自己有接诊的患者的已发布报告 + 单图分析
  影像科医生（radiologist）/ 管理员: 全量影像列表、AI 分析、发布报告

URL 路径中的 study_id 是业务表 ImagingStudy.id（自生成 UUID），
不是 DICOM StudyInstanceUID——前者用于前端引用稳定，后者用于 Orthanc 检索。
端点内部从 DB 查到 study.study_instance_uid 后再转发到 Orthanc。

端点路径里的 {filename} 历史上是 DCM 文件名，R1 后改为 Orthanc 的
SOPInstanceUID（一个 instance 唯一标识）；前端从 /frames 拿到 UID 列表后
直接用作后续端点的路径参数即可。

2026-06-11 Round 5 迁移：业务逻辑已抽到 app/services/pacs/ 包——
  dicom_service（解压/pydicom 元数据/智能抽帧）、frame_service（Orthanc 帧
  查询/渲染缓存）、analysis_service（千问 VL）、report_service（报告 ORM）。
本文件只保留：路由编排、鉴权、HTTPException、响应组装（行为零改变）。
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings
from app.core.security import get_current_user
from app.core.authz import PACS_WRITE_ROLES, assert_pacs_write, assert_patient_access
from app.database import get_db
from app.models.encounter import Encounter
from app.models.imaging import ImagingReport, ImagingStudy
from app.services.orthanc_client import orthanc_client
from app.services.redis_cache import redis_cache
from app.services.dicom_renderer import render_thumbnail, render_preview
from app.services.ai.prompts_pacs import build_study_prompt, build_image_prompt
# Round 5：PACS 业务逻辑服务包（解压/帧查询/AI 分析/报告 ORM）
from app.services.pacs import analysis_service, dicom_service, frame_service, report_service
from app.services.pacs.analysis_service import AI_FRAME_JPEG_QUALITY
from app.services.pacs.dicom_service import AUTO_ANALYZE_THRESHOLD, AUTO_SAMPLE_COUNT

logger = logging.getLogger(__name__)

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
    extract_dir = work_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1) 落盘压缩包（用原始扩展名让 7-Zip 自动识别格式）
        archive_path = work_dir / f"source.{archive_kind}"
        archive_path.write_bytes(await file.read())

        # 2) 解压（按格式自动选择 zipfile 或 7-Zip）
        dicom_service.extract_archive(archive_path, extract_dir, archive_kind)

        # 3) 找所有 DCM 文件路径（先扫一遍，不读字节）
        dcm_paths = [
            f for f in extract_dir.rglob("*")
            if f.is_file() and f.suffix.lower() == ".dcm"
        ]
        if not dcm_paths:
            raise HTTPException(400, "压缩包中未找到 DCM 文件")

        # 3.5) ⚡ 幂等快路径：只读第一个 DCM 的 metadata 拿 StudyInstanceUID 查 DB
        #      命中已存在 → 立即返回原 study_id，不读其他文件、不上传 Orthanc
        #      重传 537 帧 study 从分钟级降到亚秒级
        preflight_study_uid = dicom_service.read_preflight_study_uid(dcm_paths[0])

        if preflight_study_uid:
            existing_q = await db.execute(
                select(ImagingStudy).where(
                    ImagingStudy.study_instance_uid == preflight_study_uid
                )
            )
            existing_study = existing_q.scalar_one_or_none()
            if existing_study:
                if existing_study.patient_id != patient_id:
                    raise HTTPException(
                        409,
                        f"该影像已归属其他患者，不能再绑定到当前患者（已有 study_id={existing_study.id}）。"
                        "请先在 PACS 列表中处理原记录，或选择正确的患者。",
                    )
                return {
                    "study_id": existing_study.id,
                    "study_instance_uid": preflight_study_uid,
                    "total_frames": existing_study.total_frames,
                    "modality": existing_study.modality,
                    "body_part": existing_study.body_part,
                    "auto_select": (existing_study.total_frames or 0) <= AUTO_ANALYZE_THRESHOLD,
                    "duplicate": True,
                    "message": "该影像之前已上传过，已为你定位到原记录",
                }

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
                await frame_service.render_and_cache_all(target_study_uid, instances_for_render)

        import asyncio as _asyncio
        stow_resp, _ = await _asyncio.gather(_do_stow(), _do_render())

        # 5) 从 STOW 响应取 StudyInstanceUID（preflight 拿到的优先）
        study_uid = target_study_uid or frame_service.extract_study_uid_from_stow_response(stow_resp)
        if not study_uid:
            raise HTTPException(500, "Orthanc 上传成功但未返回 StudyInstanceUID")

        # 5.5) 把 frames_meta 存到 Redis，让 /frames 端点免去实时查 Orthanc QIDO
        # 一次 SET，后续 /frames 调用 < 50ms（vs 实时查 ~2-10s）
        import json as _json
        await redis_cache.set_bytes(
            f"pacs:frames:{study_uid}",
            _json.dumps(frames_meta).encode("utf-8"),
            ttl=settings.thumbnail_cache_ttl,
        )

        # 6) 幂等性检查：同一份 DICOM 包（同 study_instance_uid）二次上传时不再
        #    重复创建业务行，避免触发 unique 约束 IntegrityError 500。
        #    医院真实场景：医生误操作重传 / 网络重试 / 同包发给多人审核都很常见。
        existing = await db.execute(
            select(ImagingStudy).where(ImagingStudy.study_instance_uid == study_uid)
        )
        existing_study = existing.scalar_one_or_none()
        if existing_study:
            if existing_study.patient_id != patient_id:
                # 跨患者重复：DICOM UID 全局唯一，几乎一定是医生选错患者
                raise HTTPException(
                    409,
                    f"该影像已归属其他患者，不能再绑定到当前患者（已有 study_id={existing_study.id}）。"
                    "请先在 PACS 列表中处理原记录，或选择正确的患者。",
                )
            # 同患者重复 → 幂等：返回原 study_id 让前端跳转
            return {
                "study_id": existing_study.id,
                "study_instance_uid": study_uid,
                "total_frames": existing_study.total_frames,
                "modality": existing_study.modality,
                "body_part": existing_study.body_part,
                "auto_select": (existing_study.total_frames or 0) <= AUTO_ANALYZE_THRESHOLD,
                "duplicate": True,
                "message": "该影像之前已上传过，已为你定位到原记录",
            }

        # 7) 取 study 元数据（modality / body_part / series_description / 实例总数）
        meta = await frame_service.fetch_study_metadata(study_uid)

        # 8) 写业务表 ImagingStudy
        study = ImagingStudy(
            patient_id=patient_id,
            uploaded_by=current_user.id,
            study_instance_uid=study_uid,
            modality=meta.get("modality"),
            body_part=meta.get("body_part"),
            series_description=meta.get("series_description"),
            total_frames=meta.get("total_instances", 0),
            storage_dir=None,  # R1 后不再使用本地存储
            status="pending",
        )
        db.add(study)
        await db.commit()
        await db.refresh(study)

        # 注：上面 asyncio.gather 已经把所有 instance 的缩略图 + 高清预览
        # 用 pydicom 本地渲染并写入 Redis 完毕。此处不再额外预热。

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


# ─── 获取切片列表（QIDO 查 Orthanc，已搬至 frame_service）───────────────────

@router.get("/{study_id}/frames")
async def get_frames(
    study_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """返回该 study 全部 instance UID 列表 + 智能抽帧建议（用 instance_uid 标识）。

    R1 后前端不再使用文件名访问 DICOM——改为传 instance_uid 给后续端点。
    """
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")
    # 跨患者权限校验：放射科/管理员直通；普通医生必须对该患者有过接诊
    await assert_patient_access(db, study.patient_id, current_user)
    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持查看")

    # ⚡ 优先从 Redis 读 frames 元数据（上传时已写入），免去实时查 Orthanc QIDO
    import json as _json
    cache_key = f"pacs:frames:{study.study_instance_uid}"
    cached = await redis_cache.get_bytes(cache_key)
    if cached:
        try:
            instances = _json.loads(cached.decode("utf-8"))
        except Exception:
            instances = await frame_service.list_study_instances(study.study_instance_uid)
    else:
        # 老 study（R1 预热前上传的）走 Orthanc QIDO 兜底，并把结果回写 Redis
        instances = await frame_service.list_study_instances(study.study_instance_uid)
        if instances:
            await redis_cache.set_bytes(
                cache_key,
                _json.dumps(instances).encode("utf-8"),
                ttl=settings.thumbnail_cache_ttl,
            )

    total = len(instances)

    # 智能非均匀抽样（按索引→映射回 instance_uid）
    suggested_indices = dicom_service.smart_sample_indices(total, AUTO_SAMPLE_COUNT)
    suggested = [instances[i]["instance_uid"] for i in suggested_indices]

    return {
        "study_id": study_id,
        "study_instance_uid": study.study_instance_uid,
        "total": total,
        "frames": instances,  # 每项含 instance_uid + series_uid + instance_number
        "suggested": suggested,
    }


# ─── 缩略图服务（WADO render，Orthanc 自带 GDCM 渲染；series 反查搬至 frame_service）──

@router.get("/{study_id}/thumbnail/{instance_uid}")
async def get_thumbnail(
    study_id: str,
    instance_uid: str,
    wc: Optional[float] = None,
    ww: Optional[float] = None,
    series_uid: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """缩略图服务（含 PHI，必须鉴权）。

    instance_uid 是 SOPInstanceUID（DICOM 标准全局唯一），不是文件名。
    Orthanc 用 GDCM 实时渲染 + 应用窗位窗宽，无需本地缓存目录。

    series_uid 是性能优化：前端从 /frames 响应里已经拿到 series_uid，
    调本端点时一并带上，后端可免去一次反查（537 帧 study 加载从分钟级降到秒级）。

    历史漏洞修复（保留说明）：曾完全无鉴权——任何人拿到 study_id+filename
    即可下载缩略图（属于 PHI 泄露级漏洞）。已接入 assert_patient_access。
    """
    # instance_uid 是 DICOM UID，只允许数字和点号，防注入
    if not all(c.isdigit() or c == "." for c in instance_uid):
        raise HTTPException(400, "非法 instance UID")
    if series_uid and not all(c.isdigit() or c == "." for c in series_uid):
        raise HTTPException(400, "非法 series UID")
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")
    await assert_patient_access(db, study.patient_id, current_user)
    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持查看")

    # 优先用前端传的 series_uid（0 次 Orthanc 调用），没传才走兜底反查
    resolved_series = series_uid or await frame_service.resolve_instance(
        study.study_instance_uid, instance_uid
    )
    if not resolved_series:
        raise HTTPException(404, "影像帧不存在")

    # ⚡ 优化 3：Redis 优先，没命中走 pydicom 本地渲染（不再走 Orthanc 渲染）
    # 自定义窗位窗宽不缓存（key 空间无穷），实时渲染
    is_default_window = wc is None and ww is None
    cache_key = f"pacs:thumb:{study.study_instance_uid}:{instance_uid}" if is_default_window else None

    if cache_key:
        cached = await redis_cache.get_bytes(cache_key)
        if cached:
            return Response(
                content=cached,
                media_type="image/jpeg",
                headers={"Cache-Control": "private, max-age=86400", "X-Cache": "HIT"},
            )

    # 没命中 / 自定义窗位 → 拉 raw DCM + pydicom 渲染
    try:
        dcm_bytes = await orthanc_client.get_instance_dicom(
            study.study_instance_uid, resolved_series, instance_uid
        )
    except httpx.HTTPError as e:
        logger.error("pacs.fetch_dcm: failed instance=%s err=%s", instance_uid, e)
        raise HTTPException(502, "影像加载失败")

    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()
    jpeg_bytes = await loop.run_in_executor(
        None,
        lambda: render_thumbnail(dcm_bytes, window_center=wc, window_width=ww),
    )
    if not jpeg_bytes:
        raise HTTPException(500, "DICOM 渲染失败")

    # 默认窗位窗宽 → 异步写缓存（不阻塞响应）
    if cache_key:
        _asyncio.create_task(
            redis_cache.set_bytes(cache_key, jpeg_bytes, ttl=settings.thumbnail_cache_ttl)
        )

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Cache": "MISS",
        },
    )


# ─── 高清预览 JPEG（DicomViewer 主区用，1024 quality 85）─────────────────

@router.get("/{study_id}/preview/{instance_uid}")
async def get_preview(
    study_id: str,
    instance_uid: str,
    wc: Optional[float] = None,
    ww: Optional[float] = None,
    series_uid: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """高清预览 JPEG（1024×1024 quality 85，~30-80KB）。

    DicomViewer 主区 <img> 直接加载本端点 URL。比 raw DICOM (~860KB +
    cornerstone3D 客户端解码) 快得多——浏览器原生 JPEG 渲染，秒级出图。

    数据来源：
      - 上传时 backend pydicom 已渲染好高清版，存 Redis key `pacs:preview:{}:{}`
      - 没命中走 Orthanc 拉 raw DCM + pydicom 实时渲染（写回 Redis）

    自定义窗位窗宽（wc/ww）：实时渲染，不缓存。
    """
    if not all(c.isdigit() or c == "." for c in instance_uid):
        raise HTTPException(400, "非法 instance UID")
    if series_uid and not all(c.isdigit() or c == "." for c in series_uid):
        raise HTTPException(400, "非法 series UID")
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")
    await assert_patient_access(db, study.patient_id, current_user)
    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持查看")

    is_default_window = wc is None and ww is None
    cache_key = (
        f"pacs:preview:{study.study_instance_uid}:{instance_uid}"
        if is_default_window
        else None
    )

    if cache_key:
        cached = await redis_cache.get_bytes(cache_key)
        if cached:
            return Response(
                content=cached,
                media_type="image/jpeg",
                headers={"Cache-Control": "private, max-age=86400", "X-Cache": "HIT"},
            )

    resolved_series = series_uid or await frame_service.resolve_instance(
        study.study_instance_uid, instance_uid
    )
    if not resolved_series:
        raise HTTPException(404, "影像帧不存在")

    try:
        dcm_bytes = await orthanc_client.get_instance_dicom(
            study.study_instance_uid, resolved_series, instance_uid
        )
    except httpx.HTTPError as e:
        logger.error("pacs.fetch_dcm: failed instance=%s err=%s", instance_uid, e)
        raise HTTPException(502, "影像加载失败")

    import asyncio as _asyncio
    loop = _asyncio.get_event_loop()
    jpeg_bytes = await loop.run_in_executor(
        None,
        lambda: render_preview(dcm_bytes, window_center=wc, window_width=ww),
    )
    if not jpeg_bytes:
        raise HTTPException(500, "DICOM 渲染失败")

    if cache_key:
        _asyncio.create_task(
            redis_cache.set_bytes(cache_key, jpeg_bytes, ttl=settings.thumbnail_cache_ttl)
        )

    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Cache": "MISS",
        },
    )


# ─── 原始 DCM 文件服务（WADO instance，保留供 cornerstone3D 高级 viewer 用）──

@router.get("/{study_id}/dicom/{instance_uid}")
async def get_dicom_file(
    study_id: str,
    instance_uid: str,
    series_uid: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """原始 DCM 文件下载（供前端 cornerstone.js / OHIF 加载，含完整 PHI，必须鉴权）。

    R1 后从 Orthanc WADO instance 透传，FastAPI 不再持有任何 DCM 文件。
    series_uid 同 thumbnail 端点：可选，传上来免一次反查。
    """
    import time as _time
    perf_start = _time.perf_counter()
    perf = {}

    if not all(c.isdigit() or c == "." for c in instance_uid):
        raise HTTPException(400, "非法 instance UID")
    if series_uid and not all(c.isdigit() or c == "." for c in series_uid):
        raise HTTPException(400, "非法 series UID")

    t0 = _time.perf_counter()
    study = await db.get(ImagingStudy, study_id)
    perf["db_get_study"] = _time.perf_counter() - t0
    if not study:
        raise HTTPException(404, "检查不存在")

    t0 = _time.perf_counter()
    await assert_patient_access(db, study.patient_id, current_user)
    perf["assert_patient_access"] = _time.perf_counter() - t0

    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持查看")

    if not series_uid:
        t0 = _time.perf_counter()
        series_uid = await frame_service.resolve_instance(study.study_instance_uid, instance_uid)
        perf["resolve_instance"] = _time.perf_counter() - t0
    if not series_uid:
        raise HTTPException(404, "影像帧不存在")

    try:
        t0 = _time.perf_counter()
        dcm_bytes = await orthanc_client.get_instance_dicom(
            study.study_instance_uid, series_uid, instance_uid
        )
        perf["orthanc_fetch"] = _time.perf_counter() - t0
    except httpx.HTTPError as e:
        logger.error("pacs.wado: instance_fetch_failed instance=%s err=%s", instance_uid, e)
        raise HTTPException(502, "影像下载失败")

    total = _time.perf_counter() - perf_start
    if total > 1.0:  # 只记录慢请求避免日志刷屏
        logger.warning(
            "pacs.render: perf instance=%s total=%.3fs %s",
            instance_uid[-12:],
            total,
            " ".join(f"{k}={v:.3f}" for k, v in perf.items()),
        )

    return Response(content=dcm_bytes, media_type="application/dicom")


# ─── AI 分析（从 Orthanc 拉关键帧 → 千问 VL；调用逻辑搬至 analysis_service）──

class AnalyzeRequest(BaseModel):
    """前端传选中的 instance UID 列表（R1 后不再用文件名）。"""
    selected_frames: List[str]


@router.post("/{study_id}/analyze")
async def analyze_study(
    study_id: str,
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """从 Orthanc 拉选中帧 → 千问 VL 分析 → 写报告。

    R1 改造：
      - 选中帧由 instance UID 标识（不再是文件名）
      - 帧数上限按 modality 自适应（CT/MR 18、X 光 4、超声 6 等）
      - 帧像素从 Orthanc WADO render 拉（已 JPEG 编码，省一次本地转码）
    """
    assert_pacs_write(current_user)
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")
    if not study.study_instance_uid:
        raise HTTPException(410, "该检查为旧版本数据，已不支持分析")

    cap = analysis_service.frame_cap_for(study.modality)
    selected = body.selected_frames[:cap]
    if not selected:
        raise HTTPException(400, "未选中任何影像帧")

    # 从 Orthanc 拉选中帧 JPEG（series 反向索引 + WADO render，搬至 analysis_service）
    images = await analysis_service.fetch_frames_for_analysis(
        study.study_instance_uid, selected
    )
    if not images:
        raise HTTPException(400, "没有可分析的影像帧")

    # 构建 prompt + 调千问 VL（统一走 call_qwen_vl，与单图分析共用代码路径）
    prompt = build_study_prompt(study.modality, study.body_part)
    ai_result = await analysis_service.call_qwen_vl(prompt, images, max_tokens=1000)

    # 保存到数据库（unique 约束保证一个 study 至多一条 report，搬至 report_service）
    await report_service.upsert_analysis_report(
        db, study, study_id, selected, ai_result, current_user.id
    )

    return {"ai_analysis": ai_result}


# ─── 保存 / 发布报告（合并端点） ─────────────────────────────────────────────

class SaveReportRequest(BaseModel):
    """保存影像报告 body。

    - final_report : 报告正文（必填）
    - publish      : True 表示同时签发；False 仅保存草稿
    """
    final_report: str
    publish: bool = False


@router.put("/{study_id}/report")
async def save_report(
    study_id: str,
    body: SaveReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """保存或同时签发影像报告。

    Audit Round 4 G4：原本拆成 PUT /report（草稿）+ POST /publish（签发）两个端点，
    实际差异只是是否设置 is_published / published_at / published_by 三个字段，
    合并成一个端点更直观——前端只需要传 publish=True 就能签发。

    审计链设计（保持 R1 后行为一致）：
      - radiologist_id : 在 analyze_study 阶段写入，本端点 **绝不覆盖**——
        否则 "A 分析、B 复核签发" 场景会把分析人记成 B。
      - published_by   : 仅在 publish=True 时写入，记录实际签发责任人。
    """
    assert_pacs_write(current_user)
    result = await db.execute(
        select(ImagingReport).where(ImagingReport.study_id == study_id)
    )
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(404, "报告不存在，请先进行 AI 分析")

    report.final_report = body.final_report

    response: dict = {"ok": True}
    if body.publish:
        report.is_published = True
        report.published_at = datetime.utcnow()
        # 关键：只写 published_by，绝不覆盖 radiologist_id（保留分析人审计）
        report.published_by = current_user.id

        study = await db.get(ImagingStudy, study_id)
        if study:
            study.status = "published"

        response["published_at"] = report.published_at.isoformat()

    await db.commit()
    return response


# ─── 获取患者的已发布报告（临床医生用）────────────────────────────────────────

@router.get("/patient/{patient_id}/reports")
async def get_patient_reports(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 普通医生只能访问自己有 encounter 的患者
    if getattr(current_user, "role", "doctor") not in PACS_WRITE_ROLES:
        enc = await db.execute(
            select(Encounter.id).where(
                Encounter.patient_id == patient_id,
                Encounter.doctor_id == current_user.id,
            ).limit(1)
        )
        if not enc.scalar_one_or_none():
            raise HTTPException(403, "无权访问该患者影像资料")

    # 查询 + 序列化已搬至 report_service（行为零改变）
    return await report_service.list_patient_published_reports(db, patient_id)


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
        # DCM → JPEG：临时 STOW 到 Orthanc → WADO render 拿 JPEG → 删除临时 study
        # 这种"分析完即删"模式不污染 Orthanc 索引，也不需要本地 pydicom/PIL 渲染
        temp_study_uid: Optional[str] = None
        try:
            stow_resp = await orthanc_client.stow_instances([raw_bytes])
            temp_study_uid = frame_service.extract_study_uid_from_stow_response(stow_resp)
            if not temp_study_uid:
                raise HTTPException(400, "DCM 文件解析失败：Orthanc 未返回 StudyInstanceUID")
            series_list = await orthanc_client.find_series(temp_study_uid)
            if not series_list:
                raise HTTPException(400, "DCM 文件解析失败：未找到 series")
            series_uid = (series_list[0].get("0020000E", {}).get("Value") or [None])[0]
            inst_list = await orthanc_client.find_instances(temp_study_uid, series_uid)
            if not inst_list:
                raise HTTPException(400, "DCM 文件解析失败：未找到 instance")
            instance_uid = (inst_list[0].get("00080018", {}).get("Value") or [None])[0]
            img_bytes = await orthanc_client.get_instance_rendered(
                temp_study_uid, series_uid, instance_uid, quality=AI_FRAME_JPEG_QUALITY,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"DCM 文件解析失败: {e}")
        finally:
            # 无论成功失败都清理 Orthanc 临时数据，避免索引污染
            if temp_study_uid:
                try:
                    await orthanc_client.delete_study(temp_study_uid)
                except Exception as e:
                    logger.warning("pacs.upload: temp_study_cleanup_failed study=%s err=%s", temp_study_uid, e)
        mime = "image/jpeg"
    else:
        img_bytes = raw_bytes
        mime = content_type if content_type in allowed_img else "image/jpeg"

    # 构建 prompt + 调千问 VL（与 analyze_study 共用 analysis_service.call_qwen_vl）
    prompt = build_image_prompt(image_type)
    analysis = await analysis_service.call_qwen_vl(prompt, [(img_bytes, mime)], max_tokens=800)
    return {"analysis": analysis}


# ─── 删除影像研究 ───────────────────────────────────────────────────────────

@router.delete("/{study_id}")
async def delete_study(
    study_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除影像研究（含 Orthanc 端 + 业务表 + 报告，不可逆）。

    权限：影像科医生 + 管理员。
    业务约束：
      - 已发布（status=published）的 study **禁止删除**——医疗审计合规要求
        发布报告必须保留追溯链。需要修改请走"撤销发布 → 修改 → 重发布"流程
        （撤销发布功能后续 R2 再做）。
      - 未发布的 study（pending / analyzing / analyzed）允许删除。

    级联删除：
      1. Orthanc 端：调用私有 REST 删除整个 study（含所有 series/instances/files）
      2. ImagingReport：手动 DELETE（避免 ORM cascade 配置遗漏）
      3. ImagingStudy：DELETE
    """
    assert_pacs_write(current_user)
    study = await db.get(ImagingStudy, study_id)
    if not study:
        raise HTTPException(404, "检查不存在")

    if study.status == "published":
        raise HTTPException(
            409,
            "已发布的报告不能删除（医疗审计合规要求保留追溯链）。"
            "如需修改，请通过撤销发布流程。",
        )

    # 1) 删 Orthanc 端数据（先删 Orthanc 再删 DB；如果 Orthanc 失败 DB 还在，
    #    保留可重试机会；反之 DB 删了 Orthanc 失败会留孤儿数据）
    if study.study_instance_uid:
        try:
            await orthanc_client.delete_study(study.study_instance_uid)
        except Exception as e:
            logger.error("pacs.delete: orthanc_delete_failed study=%s err=%s", study.study_instance_uid, e)
            raise HTTPException(502, f"Orthanc 数据清理失败，DB 行未删除: {e}")
        # 清 Redis 里该 study 的所有缓存（frames 元数据 + 缩略图 + 高清预览）
        await redis_cache.delete(f"pacs:frames:{study.study_instance_uid}")
        await redis_cache.delete_prefix(f"pacs:thumb:{study.study_instance_uid}:")
        await redis_cache.delete_prefix(f"pacs:preview:{study.study_instance_uid}:")

    # 2) 删 ImagingReport（如有）
    from sqlalchemy import delete as _sql_delete
    await db.execute(
        _sql_delete(ImagingReport).where(ImagingReport.study_id == study_id)
    )

    # 3) 删 ImagingStudy
    await db.delete(study)
    await db.commit()

    return {"ok": True, "deleted_study_id": study_id}


# ─── 获取影像科工作列表 ──────────────────────────────────────────────────────

@router.get("/studies")
async def list_studies(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 只有放射科医生和管理员可查看全部影像列表
    if getattr(current_user, "role", "doctor") not in PACS_WRITE_ROLES:
        raise HTTPException(403, "仅放射科医生可访问影像列表")

    # 查询 + 序列化已搬至 report_service（行为零改变）
    return await report_service.list_studies_data(db, status)
