# -*- coding: utf-8 -*-
# 2026-06-11 Round 5 迁移：以下函数从 app/api/v1/pacs.py 原样搬入（纯函数搬家，行为零改变）
"""
PACS Orthanc 帧查询服务（services/pacs/frame_service.py）

职责（均为与 Orthanc 交互的无状态函数，不碰 DB、不碰请求上下文）：
  - STOW-RS 响应解析 StudyInstanceUID
  - study 元数据聚合查询（modality / body_part / series_description / 实例总数）
  - study 下 instance 列表查询（QIDO）+ instance → series 反查
  - 单个 DCM 临时 STOW → JPEG 渲染 → 即删（analyze-image 端点用）

2026-06-11 Round 6 瘦身：渲染 + Redis 缓存逻辑（render_and_cache_all 等）
已迁至同包 render_cache.py，本模块只保留纯 Orthanc 查询/转换。
"""
import logging
from typing import Optional

from fastapi import HTTPException

from app.config import settings
from app.services.orthanc_client import orthanc_client
from app.services.pacs.analysis_service import AI_FRAME_JPEG_QUALITY

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


async def dcm_to_jpeg_via_orthanc(raw_bytes: bytes) -> bytes:
    """单个 DCM → JPEG：临时 STOW 到 Orthanc → WADO render 拿 JPEG → 删除临时 study。

    analyze-image 端点（临床医生上传单张 DCM 直接分析）专用。
    这种"分析完即删"模式不污染 Orthanc 索引，也不需要本地 pydicom/PIL 渲染。

    异常语义（与原路由内联实现一致）：
      - 任一步骤失败 → HTTPException(400, "DCM 文件解析失败...")
      - 无论成功失败，finally 都清理 Orthanc 临时 study（失败仅记 warning）
    """
    temp_study_uid: Optional[str] = None
    try:
        stow_resp = await orthanc_client.stow_instances([raw_bytes])
        temp_study_uid = extract_study_uid_from_stow_response(stow_resp)
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
        return await orthanc_client.get_instance_rendered(
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
