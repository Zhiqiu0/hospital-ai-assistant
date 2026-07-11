"""Orthanc 客户端——WADO-RS 取数据（services/_orthanc_wado.py）

从 orthanc_client.py 拆出的取数据面方法（OrthancClient 的 WADO mixin）：
  - get_instance_rendered ：取单 instance 渲染图（JPEG）
  - get_instance_dicom    ：取单 instance 原始 DCM 字节
  - get_study_thumbnail   ：取 study 级缩略图

行为与原实现完全一致，仅做机械搬迁。所有方法用 self，
依赖门面提供的 self.base_url / self.dicomweb_root / self._client()。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class OrthancWadoMixin:
    """WADO-RS 取数据（供 OrthancClient 组合）。"""

    # ── WADO-RS：取数据 ──────────────────────────────────────

    async def get_instance_rendered(
        self,
        study_uid: str,
        series_uid: str,
        instance_uid: str,
        *,
        window_center: Optional[float] = None,
        window_width: Optional[float] = None,
        quality: int = 85,
        viewport: Optional[str] = None,
    ) -> bytes:
        """获取单个 instance 的渲染图（JPEG），可指定窗位窗宽和输出尺寸。

        Orthanc 用 GDCM/dcmtk 完成 DICOM → JPEG 渲染。

        viewport 参数（DICOMweb 标准）：限制输出尺寸（格式 "宽,高"），如 "256,256"。
        缩略图列表场景传 256x256，渲染时间从 ~600ms 降到 ~150ms（4 倍提升）；
        DicomViewer 主区拿原尺寸（不传 viewport）保留全像素细节。
        """
        url = (
            f"{self.dicomweb_root}/studies/{study_uid}/series/{series_uid}"
            f"/instances/{instance_uid}/rendered"
        )
        params: dict = {"quality": quality}
        if window_center is not None and window_width is not None:
            params["window"] = f"{window_center},{window_width},linear"
        if viewport:
            params["viewport"] = viewport

        async with self._client() as c:
            resp = await c.get(
                url,
                params=params,
                headers={"Accept": "image/jpeg"},
            )
            resp.raise_for_status()
            return resp.content

    async def get_instance_dicom(
        self, study_uid: str, series_uid: str, instance_uid: str
    ) -> bytes:
        """获取单个 instance 的原始 DICOM 文件（返回纯字节流，不含 multipart 包装）。

        实现选择：DICOMweb WADO-RS 单 instance 返回必须是 multipart/related，
        解析复杂；改走 Orthanc 私有 REST `/instances/{orthanc_id}/file` 直接
        拿到纯 DCM 字节。代价：与 Orthanc 绑定，未来若换 dcm4chee 需要重写
        本方法（其他端点保持 DICOMweb 标准，迁移面很小）。

        series_uid 在私有 REST 路径下不需要，但保留参数签名以便上层无感切换。
        """
        import time as _t
        async with self._client() as c:
            # 1) 通过 SOPInstanceUID 反查 Orthanc 内部 instance id
            t0 = _t.perf_counter()
            find_resp = await c.post(
                f"{self.base_url}/tools/find",
                json={
                    "Level": "Instance",
                    "Query": {
                        "StudyInstanceUID": study_uid,
                        "SOPInstanceUID": instance_uid,
                    },
                },
            )
            find_resp.raise_for_status()
            ids = find_resp.json()
            t_find = _t.perf_counter() - t0
            if not ids:
                raise HTTPException(404, "Instance 不存在")
            # 2) 拉原始 DCM 字节
            t0 = _t.perf_counter()
            file_resp = await c.get(f"{self.base_url}/instances/{ids[0]}/file")
            file_resp.raise_for_status()
            content = file_resp.content
            t_file = _t.perf_counter() - t0
            if t_find + t_file > 1.0:
                logger.warning(
                    "[PERF] orthanc_get_instance_dicom: find=%.3fs file=%.3fs total=%.3fs bytes=%d",
                    t_find, t_file, t_find + t_file, len(content),
                )
            return content

    async def get_study_thumbnail(self, study_uid: str) -> bytes:
        """获取 study 级别的缩略图（Orthanc 自动选第一帧）。"""
        url = f"{self.dicomweb_root}/studies/{study_uid}/thumbnail"
        async with self._client() as c:
            resp = await c.get(url, headers={"Accept": "image/jpeg"})
            resp.raise_for_status()
            return resp.content
