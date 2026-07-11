"""Orthanc 客户端——QIDO-RS 查询（services/_orthanc_query.py）

从 orthanc_client.py 拆出的查询面方法（OrthancClient 的 QIDO mixin）：
  - find_studies                 ：查 studies 列表
  - find_series                  ：查某 study 下所有 series
  - find_instances               ：查某 series 下所有 instances
  - find_all_instances_in_study  ：跨 series 并发取全部 instance（排序）

行为与原实现完全一致，仅做机械搬迁。所有方法用 self，
依赖门面提供的 self.dicomweb_root / self._client()。
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode


class OrthancQueryMixin:
    """QIDO-RS 查询（供 OrthancClient 组合）。"""

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
