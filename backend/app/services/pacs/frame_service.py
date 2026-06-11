# -*- coding: utf-8 -*-
# 2026-06-11 Round 5 迁移：以下函数从 app/api/v1/pacs.py 原样搬入（纯函数搬家，行为零改变）
"""
PACS Orthanc 帧查询与渲染缓存服务（services/pacs/frame_service.py）

职责（均为与 Orthanc / Redis 交互的无状态函数，不碰 DB、不碰请求上下文）：
  - STOW-RS 响应解析 StudyInstanceUID
  - study 元数据聚合查询（modality / body_part / series_description / 实例总数）
  - study 下 instance 列表查询（QIDO）+ instance → series 反查
  - 上传时用 pydicom 本地渲染缩略图/高清预览并写 Redis（优化 3 核心）

Redis key 约定（与路由层缓存读取严格一致，勿改）：
  pacs:thumb:{study_uid}:{instance_uid}    → 256 缩略图（列表用）
  pacs:preview:{study_uid}:{instance_uid}  → 1024 高清预览（DicomViewer 主区用）
"""
import logging
from typing import Optional

from app.config import settings
from app.services.dicom_renderer import render_preview, render_thumbnail
from app.services.orthanc_client import orthanc_client
from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)


def extract_study_uid_from_stow_response(stow_resp: dict) -> Optional[str]:
    """从 STOW-RS 响应解析 StudyInstanceUID。

    DICOM JSON 中 ReferencedSOPSequence (0008,1199) 是数组，每个元素的
    RetrieveURL (0008,1190) 形如 .../studies/{study_uid}/series/.../instances/...
    所有 instance 都属于同一个 study（一次上传一个 study），取第一个即可。
    """
    refs = stow_resp.get("00081199", {}).get("Value", [])
    if not refs:
        return None
    retrieve_url = refs[0].get("00081190", {}).get("Value", [None])[0]
    if not retrieve_url:
        return None
    # URL 格式: http://host/dicom-web/studies/{study_uid}/series/{s_uid}/instances/{i_uid}
    parts = retrieve_url.split("/studies/")
    if len(parts) != 2:
        return None
    return parts[1].split("/")[0]


async def render_and_cache_all(
    study_uid: str,
    instances_with_bytes: list[tuple[str, bytes]],
    concurrency: int = 8,
) -> None:
    """用 pydicom 本地渲染所有 instance 的 256 缩略图 + 1024 高清预览，写 Redis。

    这是优化 3 的核心：替代之前调 Orthanc 渲染（每张 ~150-600ms），改用
    backend 进程内 pydicom + Pillow 渲染（每张 ~3-5ms），快 30 倍。

    instances_with_bytes: [(instance_uid, dcm_bytes), ...]
    并发度通过 ThreadPoolExecutor 控制（pydicom + Pillow 释放 GIL，真并行）。

    Redis key 约定：
      pacs:thumb:{study_uid}:{instance_uid}    → 256 缩略图（列表用）
      pacs:preview:{study_uid}:{instance_uid}  → 1024 高清预览（DicomViewer 主区用）
    """
    import asyncio as _asyncio

    if not instances_with_bytes:
        return

    loop = _asyncio.get_event_loop()
    sem = _asyncio.Semaphore(concurrency)

    async def _one(iuid: str, dcm_bytes: bytes) -> None:
        async with sem:
            # 在线程池里跑 pydicom（CPU 密集，run_in_executor 释放 event loop）
            try:
                thumb_jpeg = await loop.run_in_executor(None, render_thumbnail, dcm_bytes)
                preview_jpeg = await loop.run_in_executor(None, render_preview, dcm_bytes)
            except Exception as e:
                logger.warning("pacs.preview: render_failed instance=%s err=%s", iuid, e)
                return
            if thumb_jpeg:
                await redis_cache.set_bytes(
                    f"pacs:thumb:{study_uid}:{iuid}",
                    thumb_jpeg,
                    ttl=settings.thumbnail_cache_ttl,
                )
            if preview_jpeg:
                await redis_cache.set_bytes(
                    f"pacs:preview:{study_uid}:{iuid}",
                    preview_jpeg,
                    ttl=settings.thumbnail_cache_ttl,
                )

    await _asyncio.gather(
        *[_one(iuid, dcm) for iuid, dcm in instances_with_bytes],
        return_exceptions=True,
    )
    logger.info(
        "pacs.render: done study=%s frames=%d（缩略+预览）",
        study_uid[-12:],
        len(instances_with_bytes),
    )


async def fetch_study_metadata(study_uid: str) -> dict:
    """从 Orthanc 拉 study 主要元数据：modality / body_part / series_description / 实例总数。

    取所有 series 后聚合：modality 取第一个非空值，body_part 取第一个非空值，
    series_description 拼接所有 series（去重）。

    QIDO-RS 默认不返回 BodyPartExamined / NumberOfSeriesRelatedInstances，
    必须显式 includefield。
    """
    series_list = await orthanc_client.find_series(
        study_uid,
        include_fields=["BodyPartExamined", "NumberOfSeriesRelatedInstances"],
    )
    modality = None
    body_part = None
    series_descs: list[str] = []
    total_instances = 0
    for s in series_list:
        # DICOM JSON 字段：00080060=Modality 00180015=BodyPartExamined 0008103E=SeriesDescription
        m = (s.get("00080060", {}).get("Value") or [None])[0]
        bp = (s.get("00180015", {}).get("Value") or [None])[0]
        sd = (s.get("0008103E", {}).get("Value") or [None])[0]
        # 00201209 = Number of Series Related Instances
        n = (s.get("00201209", {}).get("Value") or [0])[0]
        if m and not modality:
            modality = str(m)
        if bp and not body_part:
            body_part = str(bp)
        if sd and sd not in series_descs:
            series_descs.append(str(sd))
        try:
            total_instances += int(n)
        except (TypeError, ValueError):
            pass
    return {
        "modality": modality,
        "body_part": body_part,
        "series_description": " / ".join(series_descs)[:200] if series_descs else None,
        "total_instances": total_instances,
    }


async def list_study_instances(study_uid: str) -> list[dict]:
    """返回 study 下所有 instance 的精简信息（按 InstanceNumber 排序）。

    每条形如 {"instance_uid": "...", "series_uid": "...", "instance_number": 1}
    """
    raw = await orthanc_client.find_all_instances_in_study(study_uid)
    result = []
    for inst in raw:
        # 00080018 = SOPInstanceUID; 00200013 = InstanceNumber
        instance_uid = (inst.get("00080018", {}).get("Value") or [None])[0]
        instance_number = (inst.get("00200013", {}).get("Value") or [0])[0]
        if not instance_uid:
            continue
        result.append({
            "instance_uid": instance_uid,
            "series_uid": inst.get("_seriesInstanceUID"),
            "instance_number": int(instance_number) if instance_number else 0,
        })
    return result


async def resolve_instance(study_uid: str, instance_uid: str) -> Optional[str]:
    """通过 instance_uid 反查 series_uid（O(1) 走 Orthanc 私有 REST）。

    历史 bug：曾经遍历该 study 所有 series + 所有 instance（O(N²) 网络往返），
    537 帧 study 单张缩略图加载耗时 12 秒，整个列表加载预计 107 分钟。
    现在改用 `tools/find Level=Instance` 一次定位 instance + 一次拿 series UID，
    总共 2 次 Orthanc 调用，与帧数无关。

    更优做法：前端从 /frames 响应里就已经有 series_uid，调 thumbnail/dicom
    端点时一并传过来，免去本函数调用。本函数只在前端没传时兜底。
    """
    import httpx as _httpx
    try:
        async with _httpx.AsyncClient(
            auth=(settings.orthanc_username, settings.orthanc_password),
            timeout=10.0,
        ) as c:
            # 1) 用 SOPInstanceUID 找 Orthanc 内部 instance id
            r = await c.post(
                f"{settings.orthanc_base_url.rstrip('/')}/tools/find",
                json={
                    "Level": "Instance",
                    "Query": {
                        "StudyInstanceUID": study_uid,
                        "SOPInstanceUID": instance_uid,
                    },
                },
            )
            r.raise_for_status()
            ids = r.json()
            if not ids:
                return None
            # 2) 拿 instance 详情，里面有 ParentSeries（Orthanc 内部 series id）
            r = await c.get(f"{settings.orthanc_base_url.rstrip('/')}/instances/{ids[0]}")
            r.raise_for_status()
            parent_series = r.json().get("ParentSeries")
            if not parent_series:
                return None
            # 3) 拿 series 详情，里面有 SeriesInstanceUID（DICOM 标准 UID）
            r = await c.get(f"{settings.orthanc_base_url.rstrip('/')}/series/{parent_series}")
            r.raise_for_status()
            return r.json().get("MainDicomTags", {}).get("SeriesInstanceUID")
    except _httpx.HTTPError:
        return None
