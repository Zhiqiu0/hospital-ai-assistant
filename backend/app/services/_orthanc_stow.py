"""Orthanc 客户端——STOW 上传 + 私有 REST 管理（services/_orthanc_stow.py）

从 orthanc_client.py 拆出的上传与管理面方法（OrthancClient 的 STOW/管理 mixin）：
  - stow_instances               ：批量上传 DICOM instance（并发优化版）
  - find_orthanc_id_by_study_uid ：StudyInstanceUID → Orthanc 内部 ID
  - delete_study                 ：删除 study（含所有 series/instances/files）

行为与原实现完全一致，仅做机械搬迁。所有方法用 self，
依赖门面提供的 self.base_url / self.dicomweb_root / self.auth /
self._timeout / self._client()。
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class OrthancStowMixin:
    """STOW-RS 上传 + Orthanc 私有 REST 管理（供 OrthancClient 组合）。"""

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
