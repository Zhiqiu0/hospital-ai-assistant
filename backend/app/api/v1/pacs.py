# -*- coding: utf-8 -*-
"""
PACS 影像管理路由聚合（/api/v1/pacs/*）

R1 迁移后职责变化：
  本模块不再持有任何本地 DICOM 解析/渲染代码，所有 DICOM 操作（存储/查询/
  缩略图渲染/原图返回）全部委托给 Orthanc DICOM 服务器（DICOMweb 标准协议）。
  本模块只负责：上传适配、鉴权、AI 调用编排、报告流程、与业务表 ImagingStudy/
  ImagingReport 的关联维护。

端点列表：
  POST /upload                       上传压缩包，解压后 STOW 到 Orthanc
  GET  /{study_id}/frames            instance UID 列表 + 智能抽帧建议
  GET  /{study_id}/thumbnail|preview/{instance_uid}  缩略图 / 高清预览 JPEG
  GET  /{study_id}/dicom/{instance_uid}  原始 DCM 文件（供前端 viewer 加载）
  POST /{study_id}/analyze           从 Orthanc 拉关键帧 → 千问 VL 分析
  PUT  /{study_id}/report            保存影像报告（body.publish=True 同时签发）
  GET  /patient/{patient_id}/reports 患者已发布报告列表
  POST /analyze-image                单张 JPG/PNG/DCM 直接分析（不入库）
  DELETE /{study_id}                 删除未发布 study（Orthanc + DB 级联）
  GET  /studies                      影像科工作列表

权限分层：
  普通医生（doctor）: 只能访问自己有接诊的患者的已发布报告 + 单图分析
  影像科医生（radiologist）/ 管理员: 全量影像列表、AI 分析、发布报告

URL 路径中的 study_id 是业务表 ImagingStudy.id（自生成 UUID），不是 DICOM
StudyInstanceUID——前者前端引用稳定，后者 Orthanc 检索；端点内部从 DB 查到
study.study_instance_uid 再转发 Orthanc。路径里的 instance_uid 是
SOPInstanceUID（R1 前曾是 DCM 文件名），前端从 /frames 响应取用。

2026-06-11 Round 5 迁移 + Round 6 瘦身：业务逻辑已抽到 app/services/pacs/ 包——
  dicom_service（解压/pydicom 元数据/智能抽帧）、frame_service（Orthanc 帧查询）、
  render_cache（本地渲染 + Redis 缓存）、analysis_service（千问 VL）、
  report_service（报告 ORM / 幂等查重）。
Round 6 拆分：609 行超标，按职责拆到同目录子模块（各自建 router，本文件聚合）——
  pacs_upload   : POST /upload
  pacs_frames   : GET /{study_id}/frames|thumbnail|preview|dicom
  pacs_analysis : POST /{study_id}/analyze、POST /analyze-image
  pacs_reports  : PUT /{study_id}/report、GET /patient/.../reports、
                  DELETE /{study_id}、GET /studies
本文件只保留主 router 并 include 子路由（路径/方法/依赖零改动，行为完全一致）。
"""
from fastapi import APIRouter

# 同目录子路由（各自持有 APIRouter，端点路径与拆分前逐字一致）
from app.api.v1 import pacs_analysis, pacs_frames, pacs_reports, pacs_upload

# 主 router：仍由 app/api/v1/__init__.py 以 prefix="/pacs" 注册；
# 子路由不带额外 prefix，拼回后端点路径与原文件完全相同。
router = APIRouter()
router.include_router(pacs_upload.router)
router.include_router(pacs_frames.router)
router.include_router(pacs_analysis.router)
router.include_router(pacs_reports.router)
