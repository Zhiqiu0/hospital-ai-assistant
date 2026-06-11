# -*- coding: utf-8 -*-
# 2026-06-11 Round 5 迁移：PACS 业务逻辑从 api/v1/pacs.py 抽到本包（纯函数搬家，行为零改变）
"""
PACS 业务服务包（services/pacs/）

模块划分：
  dicom_service.py    压缩包解压（7-Zip subprocess）/ pydicom 元数据解析 / 智能抽帧
  frame_service.py    Orthanc 帧查询 / series 反查 / STOW 响应解析 / 单 DCM 临时转 JPEG
  render_cache.py     pydicom 本地渲染 + Redis 缓存读写（pacs:* key 约定集中地）
  analysis_service.py 千问 VL 调用与分析帧拉取（modality 自适应帧上限）
  report_service.py   ImagingReport / ImagingStudy 的 ORM 查询 / 幂等查重 / 状态流转

路由层（api/v1/pacs.py）只保留：上传编排、鉴权、HTTPException、响应组装。
"""
