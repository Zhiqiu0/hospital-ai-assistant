# R1：Orthanc + OHIF 迁移 Sprint

> 启动日期：2026-04-25 夜间
> 触发原因：当前 PACS 实现是私有 REST 协议，pacs.py 716 行混合了 DICOM 解析/缩略图渲染/AI 调用/路由，
> 不符合医疗影像行业标准（DICOMweb / DIMSE）。
> 趁数据库尚无生产影像数据，一次性迁到 Orthanc + OHIF，避免后期数据迁移风险。

---

## 目标架构

```
[CT/MR 设备]──DIMSE──┐
                     ├──→ [Orthanc:8042]──DICOMweb──→ [FastAPI]──→ [前端]
[第三方 PACS]────────┘     (DICOM 服务器)              (鉴权/AI/报告)   (OHIF Viewer)
                              │
                          [PostgreSQL + 文件系统]
```

**职责重新分工**：

| 职责 | 之前（自己写） | 之后 |
|---|---|---|
| DICOM 文件存储、Study/Series/Instance 索引 | uploads/pacs + ImagingStudy 表（扁平） | **Orthanc** |
| DICOM 解析 / 缩略图 / 窗位窗宽 | pydicom + Pillow（200+ 行） | **Orthanc** |
| 接受 CT 机直传 | ❌ 不支持 | **Orthanc DIMSE 4242** |
| 影像查看器 | 自写 DicomViewer.tsx (canvas) | **OHIF Viewer** |
| 用户鉴权 / AI 分析 / 报告流程 / 业务表 | FastAPI（保留） | **FastAPI（保留）** |

---

## Sprint 阶段（总估 7-10 工作日，本次熬夜推到尽可能远）

### 阶段 A：Orthanc 基础设施 ⏱️ 2-3h
- docker-compose.yml 加 orthanc service（DICOMweb plugin + PostgreSQL backend + CORS）
- Orthanc 配置文件 orthanc.json
- 验证 STOW-RS / QIDO-RS / WADO-RS 通过 curl

### 阶段 B：后端 DICOMweb 客户端 ⏱️ 1-2 天
- 新建 `backend/app/services/orthanc_client.py`：封装所有 DICOMweb HTTP 调用
- ImagingStudy 表 schema 调整：用 StudyInstanceUID（DICOM 标准 UID）替代自生 UUID
- `pacs.py` 路由全切 Orthanc：upload→STOW，frames→QIDO，thumbnail→WADO render，dicom→WADO instance
- 删除 `_render_dcm_to_jpeg / _smart_sample_frames / _generate_thumbnails / _read_dicom_metadata` 等本地实现
- pacs.py 从 716 行降到 ~250 行

### 阶段 C：前端最小适配 ⏱️ 1-2h（过渡用）
- `DicomViewer.tsx` src 切 Orthanc WADO（保留现有 canvas，用 fetchAuthedBlobUrl 模式）
- `PacsWorkbenchPage.tsx` 缩略图列表切 Orthanc WADO preview
- **里程碑 1**：后端 100% Orthanc + 前端最小可用，可 commit/部署

### 阶段 D：AI 分析改造 ⏱️ 1-2 天
- `analyze_study` 改：从 Orthanc WADO 拉关键帧（不再访问本地文件）
- modality + body_part 自适应采样规则（替代固定 18 帧）
- 报告流程不变（ImagingReport 表保留，published_by 字段保留）

### 阶段 E：OHIF Viewer 集成 ⏱️ 2-3 天
- npm install OHIF Viewer 或 Cornerstone3D
- 替换 `DicomViewer.tsx` → OHIF
- PacsWorkbenchPage 嵌入 OHIF（Study browser + Viewer）
- OHIF 直连 Orthanc DICOMweb（不经 FastAPI，性能爆炸）
- Token 注入处理

### 阶段 F：工作流优化 ⏱️ 1-2 天
- 接诊工作台展示该患者影像报告卡片（InquiryPanel 集成）
- 复诊比较视图（OHIF 原生 prior comparison）
- 放射科标注：医生在原图上画框 → 临床端可见（OHIF + DICOM SR）

### 阶段 G：清理 + 测试 + 文档 ⏱️ 0.5 天
- 删除 uploads/pacs 目录、本地 DICOM 处理代码残留
- 更新 docs/测试清单.md（重写 PACS 部分）
- 写 R1 完成报告
- **里程碑 2**：完整 Orthanc + OHIF + 工作流优化上线

---

## 数据迁移

**0 数据库存量影像**——本 Sprint 启动时点已确认 imaging_studies 表为空。
若有零星测试数据，sprint 结束时直接 TRUNCATE imaging_studies / imaging_reports，重新建账号上传测试影像。

---

## 回滚预案

- 阶段 A-D 中任意 commit 失败：git revert 回到上一稳定 commit，docker compose stop orthanc 即可回退
- 阶段 E 失败：保留 DicomViewer.tsx 不删，OHIF 集成放 feature flag 关掉
- 阶段 F 失败：单点改动可独立 revert

---

## 兼容性

- **不影响**：所有非 PACS 业务（接诊、问诊、病历、质控、AI 生成）
- **影响**：所有 /api/v1/pacs/* 端点的内部实现，API 形状保持稳定（调用方无感知）
- **新依赖**：Docker（用户机器需要装 Docker Desktop）；本地后端通过 HTTP 调 Orthanc localhost:8042

---

## 决策记录

| 决策 | 选项 | 选择 | 原因 |
|---|---|---|---|
| DICOM 服务器 | Orthanc / dcm4chee / DCMTK | **Orthanc** | 轻量、文档好、Docker 友好、AI 影像公司事实标准 |
| 前端 viewer | OHIF / Cornerstone3D / 自写 | **OHIF**（拟） | 完整 DICOM 生态、复诊比较+标注开箱即用 |
| 数据库 | Orthanc 自带 SQLite / PostgreSQL plugin | **PostgreSQL** | 与项目主库一致，便于运维 |
| 过渡策略 | 双轨保留 / 直接切换 | **直接切换** | 数据库无影像数据，无回滚成本 |
| OHIF 集成时机 | 本 Sprint 一起 / 分开做 | **本 Sprint 一起** | 用户希望"医生看到最佳形态再提反馈"，避免两次返工 |
