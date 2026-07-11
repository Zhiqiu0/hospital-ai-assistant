# -*- coding: utf-8 -*-
"""
PACS 影像帧服务子路由（切片列表 / 缩略图 / 高清预览 / 原始 DCM）

从 pacs.py 拆出（Round 6 瘦身）：负责只读的影像帧访问端点——
  GET /{study_id}/frames                     instance UID 列表 + 智能抽帧建议
  GET /{study_id}/thumbnail/{instance_uid}   缩略图 JPEG（256×256）
  GET /{study_id}/preview/{instance_uid}     高清预览 JPEG（1024×1024）
  GET /{study_id}/dicom/{instance_uid}       原始 DCM 文件（供前端 viewer 加载）
行为逐字一致，路由路径/方法/依赖零改动。本模块自建 router，由 pacs.py 拼回。
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.core.authz import assert_patient_access
from app.database import get_db
from app.models.imaging import ImagingStudy
from app.services.orthanc_client import orthanc_client
# Round 5/6：PACS 业务逻辑服务包（帧查询/渲染缓存/智能抽帧）
from app.services.pacs import dicom_service, frame_service, render_cache
from app.services.pacs.dicom_service import AUTO_SAMPLE_COUNT

logger = logging.getLogger(__name__)

router = APIRouter()


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

    # ⚡ 优先从 Redis 读 frames 元数据（上传时已写入），免去实时查 Orthanc QIDO；
    # 未命中走 QIDO 兜底并回写（已下沉 render_cache.get_frames_meta）
    instances = await render_cache.get_frames_meta(study.study_instance_uid)
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


# ─── 缩略图 / 高清预览（共享编排：校验 → 鉴权 → render_cache 缓存/渲染）────

async def _serve_frame_jpeg(
    db: AsyncSession, study_id: str, instance_uid: str, series_uid: Optional[str],
    wc: Optional[float], ww: Optional[float], current_user,
    *, kind: str, resolve_before_cache: bool,
) -> Response:
    """thumbnail / preview 两端点的共享编排（Round 6 合并，参数差异见 render_cache）。

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

    # ⚡ 优化 3：Redis 优先，没命中走 pydicom 本地渲染（不再走 Orthanc 渲染）
    jpeg_bytes, cache_status = await render_cache.fetch_render_jpeg(
        study.study_instance_uid, instance_uid, series_uid, wc, ww,
        kind=kind, resolve_before_cache=resolve_before_cache,
    )
    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400", "X-Cache": cache_status},
    )


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
    """缩略图服务（256×256，含 PHI，必须鉴权）。

    instance_uid 是 SOPInstanceUID（DICOM 标准全局唯一），不是文件名。
    series_uid 是性能优化：前端从 /frames 响应里已经拿到 series_uid，
    调本端点时一并带上，后端可免去一次反查（537 帧 study 加载从分钟级降到秒级）。
    """
    return await _serve_frame_jpeg(
        db, study_id, instance_uid, series_uid, wc, ww, current_user,
        kind="thumb", resolve_before_cache=True,
    )


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
    上传时 backend pydicom 已渲染好高清版存 Redis；自定义窗位窗宽实时渲染不缓存。
    """
    return await _serve_frame_jpeg(
        db, study_id, instance_uid, series_uid, wc, ww, current_user,
        kind="preview", resolve_before_cache=False,
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
