"""Orthanc DICOMweb 客户端（services/orthanc_client.py）

R1 迁移：把 pacs.py 里所有"自己解析 DICOM / 渲染缩略图 / 管理切片"的逻辑
全部委托给 Orthanc DICOM 服务器（https://orthanc.uclouvain.be）。
本模块封装 DICOMweb 标准协议（STOW-RS / QIDO-RS / WADO-RS）的 HTTP 调用。

为什么走 DICOMweb 而不是 Orthanc 私有 REST：
  - DICOMweb 是 IHE 国际标准，前端 OHIF Viewer / 第三方阅片软件都直接支持
  - Orthanc 私有 REST 仅 Orthanc 系生态用，绑死供应商
  - 未来若换 dcm4chee / GCP Healthcare API，DICOMweb 调用代码完全不变

端点约定（DICOMweb / Orthanc）：
  STOW-RS:   POST /dicom-web/studies                                 上传 instance(s)
  QIDO-RS:   GET  /dicom-web/studies?...                             查 studies
             GET  /dicom-web/studies/{study_uid}/series              查 series
             GET  /dicom-web/studies/{study_uid}/series/{s_uid}/instances  查 instances
  WADO-RS:   GET  /dicom-web/studies/{study_uid}/series/{s_uid}/instances/{i_uid}/rendered  渲染图
             GET  /dicom-web/studies/{study_uid}/series/{s_uid}/instances/{i_uid}           原始 DCM
             GET  /dicom-web/studies/{study_uid}/thumbnail                                  缩略图
  Orthanc 扩展（私有，仅当 DICOMweb 不够时使用）:
             POST /tools/find                                          复杂查询
             DELETE /studies/{orthanc_study_id}                       删除 study
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.config import settings

logger = logging.getLogger(__name__)


class OrthancClient:
    """Orthanc DICOMweb HTTP 客户端。

    使用 Basic Auth 鉴权（凭证来自 settings.orthanc_username/password）。
    所有方法都是 async，超时统一 60s（影像传输偶尔较慢）。
    """

    def __init__(self):
        self.base_url = settings.orthanc_base_url.rstrip("/")
        self.dicomweb_root = f"{self.base_url}/dicom-web"
        self.auth = (settings.orthanc_username, settings.orthanc_password)
        # 影像数据传输偶尔到几十 MB，超时给 60s
        self._timeout = httpx.Timeout(60.0, connect=5.0)

    def _client(self) -> httpx.AsyncClient:
        """每次调用新建 AsyncClient（短连接更稳，影像传输不需要长连接复用）。"""
        return httpx.AsyncClient(auth=self.auth, timeout=self._timeout)

    # ── STOW-RS：上传 ────────────────────────────────────────

    async def stow_instances(
        self, dicom_bytes_list: list[bytes], *, concurrency: int = 8
    ) -> dict:
        """批量上传 DICOM instance 到 Orthanc（并发优化版）。

        实现选择：用 Orthanc 私有 REST `POST /instances` 单 instance 上传 +
        asyncio.gather 并发，而不是 DICOMweb STOW-RS 一次性 multipart 发全部。
        理由：
          - STOW-RS multipart 的 537 个 instance body 拼接太大（120MB+），
            Orthanc 单线程串行解析每个 instance，处理时间是顺序累加
          - 私有 REST 单 instance + 8 路并发，Orthanc 内部能并发解析，
            537 帧 study 从 60s 降到 ~10s，实测 5x 提升
          - 代价：与 Orthanc 绑定（不能直接换 dcm4chee），但单上传一个动作
            未来切换的工作量很小

        Args:
            dicom_bytes_list: 每个元素是一个 .dcm 文件的二进制内容
            concurrency: 并发数（默认 8 路；超过 16 通常无收益）

        Returns:
            兼容 STOW-RS 响应格式的 dict（含 ReferencedSOPSequence + RetrieveURL），
            供上层 `_extract_study_uid_from_stow_response` 解析

        Raises:
            HTTPException: 全部上传失败
        """
        if not dicom_bytes_list:
            raise HTTPException(400, "没有可上传的 DICOM 文件")

        import asyncio as _asyncio
        sem = _asyncio.Semaphore(concurrency)
        # 共享一个 AsyncClient（连接池复用，避免 N 次 SSL 握手 + auth 协商）
        client = httpx.AsyncClient(auth=self.auth, timeout=self._timeout)

        async def _one(dcm_bytes: bytes) -> Optional[dict]:
            async with sem:
                try:
                    r = await client.post(
                        f"{self.base_url}/instances",
                        content=dcm_bytes,
                        headers={"Content-Type": "application/dicom"},
                    )
                    if r.status_code not in (200, 202):
                        logger.warning("instance upload failed: %d %s",
                                       r.status_code, r.text[:200])
                        return None
                    return r.json()
                except httpx.HTTPError as e:
                    logger.warning("instance upload exception: %s", e)
                    return None

        try:
            results = await _asyncio.gather(*[_one(d) for d in dicom_bytes_list])
        finally:
            await client.aclose()

        successes = [r for r in results if r and r.get("ParentStudy")]
        if not successes:
            raise HTTPException(500, "DICOM 上传到 Orthanc 失败：所有 instance 都未成功")

        # 反查 StudyInstanceUID（私有 REST 给的是 Orthanc 内部 study id）
        parent_study_id = successes[0]["ParentStudy"]
        async with self._client() as c:
            r = await c.get(f"{self.base_url}/studies/{parent_study_id}")
            r.raise_for_status()
            study_uid = r.json().get("MainDicomTags", {}).get("StudyInstanceUID")
        if not study_uid:
            raise HTTPException(500, "Orthanc 上传成功但未能解析 StudyInstanceUID")

        # 包装成 STOW-RS 响应格式（保持调用方兼容，
        # _extract_study_uid_from_stow_response 解析 RetrieveURL 拿 study_uid）
        return {
            "00081199": {
                "Value": [
                    {
                        "00081190": {
                            "Value": [
                                f"{self.dicomweb_root}/studies/{study_uid}"
                                f"/series/-/instances/-"
                            ]
                        }
                    }
                ]
            }
        }

    # ── QIDO-RS：查询 ────────────────────────────────────────

    async def find_studies(self, filters: Optional[dict] = None) -> list[dict]:
        """查询 studies 列表（QIDO-RS）。

        Args:
            filters: DICOM tag → value，如 {"PatientID": "P001"}

        Returns:
            DICOM JSON 数组，每项是一个 study 的 metadata
        """
        url = f"{self.dicomweb_root}/studies"
        if filters:
            url += "?" + urlencode(filters)
        async with self._client() as c:
            resp = await c.get(url, headers={"Accept": "application/dicom+json"})
            if resp.status_code == 204:
                return []
            resp.raise_for_status()
            return resp.json()

    async def find_series(
        self, study_uid: str, *, include_fields: Optional[list[str]] = None
    ) -> list[dict]:
        """查询某个 study 下的所有 series。

        QIDO-RS 默认只返回 standard tags（不含 BodyPartExamined / NumberOfSeriesRelatedInstances 等），
        通过 include_fields 显式声明额外字段——传 DICOM tag 名（如 "BodyPartExamined"）
        或 8 位 16 进制 tag（如 "00180015"）。
        """
        url = f"{self.dicomweb_root}/studies/{study_uid}/series"
        if include_fields:
            url += "?" + urlencode({"includefield": ",".join(include_fields)})
        async with self._client() as c:
            resp = await c.get(url, headers={"Accept": "application/dicom+json"})
            if resp.status_code == 204:
                return []
            resp.raise_for_status()
            return resp.json()

    async def find_instances(self, study_uid: str, series_uid: str) -> list[dict]:
        """查询某个 series 下的所有 instances（切片）。"""
        async with self._client() as c:
            resp = await c.get(
                f"{self.dicomweb_root}/studies/{study_uid}/series/{series_uid}/instances",
                headers={"Accept": "application/dicom+json"},
            )
            if resp.status_code == 204:
                return []
            resp.raise_for_status()
            return resp.json()

    async def find_all_instances_in_study(self, study_uid: str) -> list[dict]:
        """跨所有 series 取出该 study 全部 instance（按 InstanceNumber 排序）。

        实现：DICOMweb QIDO 走 series 列表 → 每个 series **并发**查 instance：
          - asyncio.gather 同时打 N 路请求（N = series 数）
          - 11 series × 顺序串行 24s 降到 11 series 并发 2-3s
          - 用 DICOMweb 而非 Orthanc 私有 REST 是因为后者 expand=true 在
            大 series（200+ instance）上会触发 Orthanc 端超时断连

        返回值统一成 DICOMweb JSON 格式（保持调用方兼容）：
          - 00080018 = SOPInstanceUID
          - 00200013 = InstanceNumber
          - _seriesInstanceUID = 该 instance 所属 series 的 SeriesInstanceUID
        """
        import asyncio as _asyncio

        # 1) 拿所有 series（一次 QIDO，返回 series 列表 + SeriesInstanceUID）
        series_list = await self.find_series(study_uid)
        if not series_list:
            return []

        # 2) 并发查每个 series 的 instance
        async def _one(series: dict) -> list[dict]:
            series_uid = (series.get("0020000E", {}).get("Value") or [None])[0]
            if not series_uid:
                return []
            instances = await self.find_instances(study_uid, series_uid)
            for inst in instances:
                inst["_seriesInstanceUID"] = series_uid
            return instances

        results_per_series = await _asyncio.gather(*[_one(s) for s in series_list])

        # 3) 扁平化 + 按 InstanceNumber 排序
        all_instances = [inst for sub in results_per_series for inst in sub]
        all_instances.sort(
            key=lambda i: int(i.get("00200013", {}).get("Value", [0])[0])
            if i.get("00200013")
            else 0
        )
        return all_instances

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

    # ── Orthanc 私有 REST：管理操作 ──────────────────────────

    async def find_orthanc_id_by_study_uid(self, study_uid: str) -> Optional[str]:
        """通过 StudyInstanceUID 查 Orthanc 内部 ID（删除/管理操作要用）。"""
        async with self._client() as c:
            resp = await c.post(
                f"{self.base_url}/tools/find",
                json={
                    "Level": "Study",
                    "Query": {"StudyInstanceUID": study_uid},
                },
            )
            resp.raise_for_status()
            ids = resp.json()
            return ids[0] if ids else None

    async def delete_study(self, study_uid: str) -> bool:
        """删除某个 study（含所有 series/instances/files）。"""
        orthanc_id = await self.find_orthanc_id_by_study_uid(study_uid)
        if not orthanc_id:
            return False
        async with self._client() as c:
            resp = await c.delete(f"{self.base_url}/studies/{orthanc_id}")
            resp.raise_for_status()
            return True

    async def health_check(self) -> bool:
        """探活：调 /system 接口验证 Orthanc 在跑且认证 OK。"""
        try:
            async with self._client() as c:
                resp = await c.get(f"{self.base_url}/system", timeout=5.0)
                return resp.status_code == 200
        except Exception:
            return False


# 全局单例（FastAPI dependency 直接 import 用）
orthanc_client = OrthancClient()
