# Audit Round 4 重构接力文档（v2）

> 产出日期：2026-04-29
> 用途：跨会话接力。新会话开始时让 Claude 读这一份，立刻知道当前进度 + 边界 + 下一步。
> 原始 backlog：参见 `docs/audit_round_4_backlog.md`
> 上一版：v1（2026-04-28，已被本版替换）

---

## ⚠️ 重要约束（不要忘）

1. **不要中途 git commit**。所有改动做完后**一次性** 在新分支上 commit + push + 开 PR，让 GitHub CI 把关 + 自动 deploy。**走 PR 流程**，不要直 push main。
2. **不要返工已完成项**。M1 / G1+G6+G7 / M3 / M2 / M5 / M6 的 11 个文件都已完成且测试全过，下一会话不要重做。
3. **每完成一项立即跑测试**，绿了再做下一项。任何项失败必须停下排查。
4. **服务启动归用户**：Orthanc docker / 后端 uvicorn / 前端 vite 这些**必须等用户手动启动**才能做端到端测试。
5. **大文件写入分段**：单次 Write > 200 行会断连，用 Edit 增量改 / 或者分两轮 Write。
6. **大量输出分段交付**：M6 拆 11 个文件那种工作量，每完成 1-2 个跟用户汇报一次，不要积累后再统一汇报。

---

## ✅ 已完成（不要重做）

### 上一会话（2026-04-28）
- **G1+G6+G7 暖身**：删 ResumeDrawer + PACS PRIVILEGED_ROLES 统一到 authz + 清历史注释
- **M1 真拆 store**：拆 5 个子 store（types/inquiry/record/qc/aiSuggestion）+ 30 consumer 全迁移

### 本会话（2026-04-29）
- **M3** encounter_service.get_workspace_snapshot 拆解
- **M2** medical_record_service N+1 查询优化
- **M5** 补 18 个 service 测试（snapshot 10 + quick_save 8）
- **M6** 拆 16 个超长前端文件（详见下方两张表 — 11 个主拆 + 5 个边缘补拆）
- **G2** PACS analyze 公共代码抽取（_call_qwen_vl + prompts_pacs）
- **G3** PACS 7-zip startup 检测（module-level SEVENZIP_PATH）
- **G4** PACS save_report / publish_report 合并为 PUT /report?publish=true
- **G5** PACS DCM 临时文件 try/finally（R1 迁移已修，本轮核对）
- **G8** tests/conftest.py 隔离 AsyncSessionLocal（顶部注入 DATABASE_URL=sqlite memory）

### 验证状态
- backend pytest: **61/61 全绿**（含本轮新增 18 用例）
- frontend tsc --noEmit: **0 错**
- frontend vitest: **39/39 全绿**

---

## 📋 本会话 M6 拆分清单（已完成 11 个）

| 文件 | 原行数 | 拆后主文件 | 抽出物 |
|---|---|---|---|
| `pages/admin/StatsPage.tsx` | 680 | 78 | `pages/admin/stats/{constants.ts,OverviewTab,UsageTab,QCTab,TokenTab}.tsx` |
| `hooks/useRecordEditor.ts` | 474 | 384 | `services/streamSSE.ts` + `utils/recordSections.ts` |
| `components/workbench/InquiryPanel.tsx` | 482 | 168 | `inquiry/{Header,TimeFields,BasicFields,PhysicalExam,SaveBar}.tsx` |
| `pages/PacsWorkbenchPage.tsx` | 728 | 297 | `pages/pacs/{types.ts,AuthedThumbnail,StudyListStage,SelectFramesStage,AnalyzingStage,ReportStage}.tsx` |
| `components/workbench/NewInpatientEncounterModal.tsx` | 623 | 201 | `newInpatient/{constants.ts,SectionLabel,SelectedPatientCard,NewPatientFields,SearchStep,FormStep}.tsx` |
| `pages/WorkbenchPage.tsx` | 509 | 278 | `components/workbench/{WorkbenchHeader,NoPatientOverlay}.tsx` |
| `components/workbench/DicomViewer.tsx` | 444 | 211 | `hooks/useDicomViewer.ts` + `DicomViewerToolbar.tsx` |
| `components/workbench/NewEncounterModal.tsx` | 430 | 201 | `newEncounter/{SearchStep,NewPatientFields,SelectedPatientCard}.tsx` |
| `pages/InpatientWorkbenchPage.tsx` | 419 | 342 | `components/workbench/InpatientRightPanel.tsx` |
| `components/workbench/PatientHistoryDrawer.tsx` | 418 | 221 | `patientHistory/{sceneTag.ts,PatientCardHeader,PatientPickerList,RecordList}.tsx` |
| `hooks/useInquiryPanel.ts` | 370 | 285 | `utils/inquirySync.ts` |

合计新增 30+ 个文件，业务逻辑等价，未改动行为。

---

## 📋 本会话 M6 边缘 5 个文件补拆（一并搞定）

| 文件 | 原行数 | 拆后主文件 | 抽出物 |
|---|---|---|---|
| `components/workbench/RecordEditor.tsx` | 341 | 92 | `recordEditor/{RecordEditorToolbar,RecordEditorStatusBar}.tsx` |
| `components/workbench/QCIssuePanel.tsx` | 329 | 195 | `qcIssue/{qcConstants.ts,QCIssueItem.tsx}` |
| `components/workbench/PatientProfileCard.tsx` | 345 | 138 | `patientProfile/{staleness.ts,PatientProfileHeader,PatientProfileField}.tsx` |
| `hooks/useInpatientInquiryPanel.ts` | 303 | 192 | `utils/inpatientInquirySync.ts` |
| `hooks/useVoiceInputCard.ts` | 415 | 309 | `services/voiceTranscriptApi.ts` + `hooks/useVoiceTranscriptPersistence.ts` |

合计 16 个 M6 文件全部拆完。无遗留。

---

## ✅ 本会话 G2-G8 已完成

- **G2** PACS analyze 公共代码抽取
  - 新文件 `backend/app/services/ai/prompts_pacs.py` 含 `build_study_prompt` / `build_image_prompt`
  - 新增 `_call_qwen_vl(prompt, images, max_tokens)` 公共函数
  - analyze_study + analyze_image 两个端点共用同一 LLM 调用 + prompt 模板
- **G3** PACS 7-zip startup 检测：module-level `SEVENZIP_PATH = _find_sevenzip()`，请求路径不再 glob；未检测到 startup log warn 一次
- **G4** PACS save_report / publish_report 合并：保留 `PUT /pacs/{study_id}/report`，body 加 `publish: bool = False`；删除 `POST /publish`；前端 `PacsWorkbenchPage.publishReport` 已迁
- **G5** PACS DCM 临时文件 try/finally：R1 迁移已修（analyze_image 用 Orthanc 临时 STOW + finally delete_study；upload_study 用 try/finally + shutil.rmtree），全 backend 已无 `os.unlink` 遗留
- **G8** tests/conftest.py 隔离 AsyncSessionLocal：顶部注入 `DATABASE_URL=sqlite+aiosqlite:///:memory:`（在 import app.* 之前），使 `app.database.AsyncSessionLocal` 一开始就是 SQLite engine——audit_service / task_logger 也走 SQLite，不再连开发 PostgreSQL

---

## ⏸️ 待做任务（下轮起点）

> Audit Round 4 已无 backlog 项；本节留给下次发现的新问题。

---

## 🧪 端到端测试（G 系列做完后跑）

**前置条件**（用户手动启动）：
1. Orthanc docker（镜像已下完，`docker compose up -d orthanc`）
2. 后端 `uvicorn --reload`（端口 8010）
3. 前端 `npm run dev`（端口 5174）
4. 本地 Redis 已在跑（D:\APP\DevelopApp\Redis，6379）
5. 本地 PG（容器 `hospital-ai-assistant-db-1`，5432，已建 `orthanc` 数据库）

**用 Playwright MCP 跑核心流程**（snapshot 模式）：
1. 登录 → 工作台
2. 新建接诊 → 填问诊 → 保存 → AI 生成病历 → 流式输出完成
3. **切换患者**（M1 核心防回归）：A → B 检查 inquiry/record/qc/aiSuggestion 是否清干净
4. AI 质控 → 修复一条 issue → 写入病历
5. 出具最终病历 → 签发后锁定不可改
6. **PACS 路径**：上传影像 → 选关键帧 → AI 分析 → 发布报告（验证 M6 PacsWorkbench 拆分）

**验收**：核心流程跑完，console 无 error；任何步骤失败立即停下排查。

---

## 📋 最后一步：开 PR + 等 CI 绿 + 合并

**全部完成后**才执行（顺序不要乱）：

```bash
# 1. 提交前最后跑一次三项全绿确认
cd backend && PYTHONUTF8=1 venv/Scripts/python.exe -m pytest -q
cd ../frontend && npx tsc --noEmit && npx vitest run

# 2. 切新分支（不要直接在 main 上提交）
git checkout -b audit-round-4-refactor

# 3. 一次性提交所有改动
git add -A
git status  # 检查 staged 列表，确认没有 .env / 凭证 / 大二进制误入
git commit -m "$(cat <<'EOF'
feat: Audit Round 4 M1-M6+G 架构整改

- M1: workbenchStore 拆 5 个子 store，30 consumer 迁移
- M2: medical_record_service N+1 查询优化（window function + LEFT JOIN）
- M3: encounter_service.get_workspace_snapshot 拆解（≤50 行 + 减查询）
- M5: 补 18 个 service 关键测试（snapshot + quick_save）
- M6: 拆 11 个超长前端文件（StatsPage/PacsWorkbench/InquiryPanel 等）
- G1-G8: PACS/角色/注释/孤儿组件/测试隔离 等清理

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

# 4. 推到 GitHub
git push -u origin audit-round-4-refactor

# 5. 开 PR
gh pr create --base main --head audit-round-4-refactor \
  --title "feat: Audit Round 4 M1-M6+G 架构整改" \
  --body "..."

# 6. 等 CI 绿
gh pr checks --watch

# 7. CI 绿后合并到 main（触发 deploy.yml 自动部署 mediscribe.cn）
gh pr merge --squash --delete-branch
```

---

## 🆕 新会话开始时怎么 pick up

**用户在新会话第一句话就发**：

> 继续 Audit Round 4 重构。先读 `docs/audit_round_4_handoff.md` 拿到完整上下文（已完成项 + 待办 + 边界），从 G2 开始干（M3/M2/M5/M6 都已完成不要重做）。每项做完跑测试 → 绿了再下一项。最后端到端测试 + 在新分支上一次性提交 + 开 PR + 等 CI 绿 + squash merge（不要直 push main）。

**Claude 应该做的**：
1. 读这份 handoff 文档
2. 确认当前 git 状态（`git status` 应该有大量 untracked + modified 文件 = 本会话产出）
3. **不要重做** M1 / G1+G6+G7 / M3 / M2 / M5 / M6
4. 从 G2 开始干，按顺序 G2 → G3 → G4 → G5 → G8 → 端到端测试 → 统一 commit + PR
5. 每项做完更新 todo + 跑测试

---

## 📝 本会话遗留状态

- Backlog 13 项全部完成（M1 / M2 / M3 / M5 / M6 / G1-G8）
- 三项验证全绿：backend 61/61 pytest + frontend tsc 0 错 + frontend vitest 39/39
- 端到端：登录 → 工作台路由 + 急诊路由切换走通，console 无运行时错误（深度功能流程留给用户在浏览器侧验证）
- **下一步**：等用户浏览器深度 E2E（接诊 / AI 生成 / 切换患者 / 质控 / 出具 / PACS）验收通过 → 切新分支 + commit + PR + CI 绿 + squash merge


