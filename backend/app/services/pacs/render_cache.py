# -*- coding: utf-8 -*-
# 2026-06-11 Round 6 瘦身：渲染 + Redis 缓存相关逻辑从 frame_service / api/v1/pacs.py 集中到本模块
"""
PACS 渲染缓存服务（services/pacs/render_cache.py）

职责（pydicom 本地渲染 + Redis 缓存读写，所有 pacs:* 缓存 key 约定集中在此）：
  - 上传时批量本地渲染缩略图/高清预览并写 Redis（render_and_cache_all，优化 3 核心）
  - thumbnail / preview 端点共享的"缓存优先 → 实时渲染"取图流程（fetch_render_jpeg）
  - /frames 端点的帧元数据缓存读写（cache_frames_meta / get_frames_meta）
  - 删除 study 时清理该 study 全部缓存（clear_study_cache）

Redis key 约定（勿改，老缓存数据依赖）：
  pacs:frames:{study_uid}                  → 帧元数据 JSON（/frames 端点用）
  pacs:thumb:{study_uid}:{instance_uid}    → 256 缩略图（列表用）
  pacs:preview:{study_uid}:{instance_uid}  → 1024 高清预览（DicomViewer 主区用）
"""
import asyncio
import json
import logging
from typing import Optional

import httpx
from fastapi import HTTPException

from app.config import settings
from app.services.dicom_renderer import render_preview, render_thumbnail
from app.services.orthanc_client import orthanc_client
from app.services.pacs import frame_service
from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)

# kind → 渲染函数（kind 同时是缓存 key 前缀）：thumbnail / preview 两个端点唯一的差异点
_RENDER_PROFILES = {
    "thumb": render_thumbnail,    # 256×256 quality 75（列表缩略图）
    "preview": render_preview,    # 1024×1024 quality 85（主区高清预览）
}


async def render_and_cache_all(
    study_uid: str,
    instances_with_bytes: list[tuple[str, bytes]],
    concurrency: int = 8,
) -> None:
    """用 pydicom 本地渲染所有 instance 的 256 缩略图 + 1024 高清预览，写 Redis。

    这是优化 3 的核心：替代之前调 Orthanc 渲染（每张 ~150-600ms），改用
    backend 进程内 pydicom + Pillow 渲染（每张 ~3-5ms），快 30 倍。

    instances_with_bytes: [(instance_uid, dcm_bytes), ...]
    并发度通过 Semaphore + 线程池控制（pydicom + Pillow 释放 GIL，真并行）。
    """
    if not instances_with_bytes:
        return

    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(concurrency)

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

    await asyncio.gather(
        *[_one(iuid, dcm) for iuid, dcm in instances_with_bytes],
        return_exceptions=True,
    )
    logger.info(
        "pacs.render: done study=%s frames=%d（缩略+预览）",
        study_uid[-12:],
        len(instances_with_bytes),
    )


async def fetch_render_jpeg(
    study_uid: str,
    instance_uid: str,
    series_uid: Optional[str],
    wc: Optional[float],
    ww: Optional[float],
    *,
    kind: str,
    resolve_before_cache: bool,
) -> tuple[bytes, str]:
    """thumbnail / preview 两端点共享的取图流程，返回 (jpeg_bytes, 缓存状态 HIT/MISS)。

    流程（与原两份路由内联实现逐行一致，行为零改变）：
      1. 默认窗位窗宽 → 查 Redis 缓存（自定义 wc/ww 不缓存，key 空间无穷）
      2. 没命中 → series 反查兜底（前端传了 series_uid 则 0 次 Orthanc 调用）
         → 从 Orthanc 拉 raw DCM → pydicom 线程池渲染 → 异步回写缓存

    kind: "thumb"（256 缩略图）或 "preview"（1024 高清预览），
          同时决定渲染函数与缓存 key 前缀（pacs:thumb: / pacs:preview:）。
    resolve_before_cache: 历史顺序差异——thumbnail 端点先做 series 反查再查缓存，
          preview 端点先查缓存命中即返回（不反查）。保持各自原有语义。
    """
    render_func = _RENDER_PROFILES[kind]
    # 自定义窗位窗宽不缓存（key 空间无穷），实时渲染
    is_default_window = wc is None and ww is None
    cache_key = f"pacs:{kind}:{study_uid}:{instance_uid}" if is_default_window else None

    resolved_series = series_uid
    if resolve_before_cache:
        # 优先用前端传的 series_uid（0 次 Orthanc 调用），没传才走兜底反查
        resolved_series = series_uid or await frame_service.resolve_instance(study_uid, instance_uid)
        if not resolved_series:
            raise HTTPException(404, "影像帧不存在")

    if cache_key:
        cached = await redis_cache.get_bytes(cache_key)
        if cached:
            return cached, "HIT"

    if not resolve_before_cache:
        resolved_series = series_uid or await frame_service.resolve_instance(study_uid, instance_uid)
        if not resolved_series:
            raise HTTPException(404, "影像帧不存在")

    # 没命中 / 自定义窗位 → 拉 raw DCM + pydicom 渲染
    try:
        dcm_bytes = await orthanc_client.get_instance_dicom(study_uid, resolved_series, instance_uid)
    except httpx.HTTPError as e:
        logger.error("pacs.fetch_dcm: failed instance=%s err=%s", instance_uid, e)
        raise HTTPException(502, "影像加载失败")

    loop = asyncio.get_event_loop()
    jpeg_bytes = await loop.run_in_executor(
        None,
        lambda: render_func(dcm_bytes, window_center=wc, window_width=ww),
    )
    if not jpeg_bytes:
        raise HTTPException(500, "DICOM 渲染失败")

    # 默认窗位窗宽 → 异步写缓存（不阻塞响应）
    if cache_key:
        asyncio.create_task(
            redis_cache.set_bytes(cache_key, jpeg_bytes, ttl=settings.thumbnail_cache_ttl)
        )
    return jpeg_bytes, "MISS"


async def cache_frames_meta(study_uid: str, frames_meta: list[dict]) -> None:
    """把帧元数据写入 Redis，让 /frames 端点免去实时查 Orthanc QIDO。

    一次 SET，后续 /frames 调用 < 50ms（vs 实时查 ~2-10s）。
    """
    await redis_cache.set_bytes(
        f"pacs:frames:{study_uid}",
        json.dumps(frames_meta).encode("utf-8"),
        ttl=settings.thumbnail_cache_ttl,
    )


async def get_frames_meta(study_uid: str) -> list[dict]:
    """读取帧元数据：⚡ Redis 优先（上传时已写入），未命中走 Orthanc QIDO 兜底并回写。

    缓存值损坏（JSON 解析失败）同样回退 QIDO（不回写，保持原行为）。
    """
    cached = await redis_cache.get_bytes(f"pacs:frames:{study_uid}")
    if cached:
        try:
            return json.loads(cached.decode("utf-8"))
        except Exception:
            return await frame_service.list_study_instances(study_uid)
    # 老 study（R1 预热前上传的）走 Orthanc QIDO 兜底，并把结果回写 Redis
    instances = await frame_service.list_study_instances(study_uid)
    if instances:
        await cache_frames_meta(study_uid, instances)
    return instances


async def clear_study_cache(study_uid: str) -> None:
    """清 Redis 里该 study 的所有缓存（frames 元数据 + 缩略图 + 高清预览）。"""
    await redis_cache.delete(f"pacs:frames:{study_uid}")
    await redis_cache.delete_prefix(f"pacs:thumb:{study_uid}:")
    await redis_cache.delete_prefix(f"pacs:preview:{study_uid}:")
