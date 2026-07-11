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

拆分（超标文件拆分：367 行 → 本门面 + 3 mixin）：
  - _orthanc_query.OrthancQueryMixin ：QIDO-RS 查询
  - _orthanc_wado.OrthancWadoMixin   ：WADO-RS 取数据
  - _orthanc_stow.OrthancStowMixin   ：STOW 上传 + 私有 REST 管理
兼容：单例 `orthanc_client` 与其全部方法保持不变，
      `from app.services.orthanc_client import orthanc_client` 用法照旧。
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.services._orthanc_query import OrthancQueryMixin
from app.services._orthanc_stow import OrthancStowMixin
from app.services._orthanc_wado import OrthancWadoMixin

logger = logging.getLogger(__name__)


class OrthancClient(OrthancQueryMixin, OrthancWadoMixin, OrthancStowMixin):
    """Orthanc DICOMweb HTTP 客户端。

    使用 Basic Auth 鉴权（凭证来自 settings.orthanc_username/password）。
    所有方法都是 async，超时统一 60s（影像传输偶尔较慢）。

    具体方法实现分布在上面 3 个 mixin 中，本类只负责组合 + 持有连接配置。
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
