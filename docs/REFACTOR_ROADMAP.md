---
name: 重构路线图（当前进度）
description: MediScribe 全栈重构的分阶段路线图和当前进度，新会话需先读此文件
type: project
originSessionId: c4095611-8362-4ebf-a8a4-a56101b96ebf
---
# 🎯 目标

医疗 AI 系统 MediScribe 在做全栈重构，地基先打好避免反复重构。整体两大阶段：

- **Round 1-2**：医疗领域地基（纵向患者档案 + domain 层 + 住院时间轴）
- **Phase 2-4**：UI 体验升级

## 架构决策（已定，不再讨论）

符合 HL7 FHIR 的纵向患者档案：`Patient` · `PatientProfile`（新，过敏/既往/家族/用药跟随患者）· `Encounter` · `MedicalRecord`。

门诊+住院共用通用领域地基。门诊急诊已合并（`WorkbenchPage` + `mode` 参数）。住院独立建时间轴。

## ✅ 已完成

### 后端（Round 1.1-1.3）
- `app/models/patient.py` 加 9 个 `profile_*` 字段
- `app/schemas/patient.py` 加 `PatientProfile`
- `app/services/patient_service.py` 加 `get_profile` / `update_profile`
- `app/api/v1/patients.py` 加 `GET/PUT /patients/:id/profile`
- `app/api/v1/encounters.py` 的 `quick-start` 返回 `patient_profile`
- `app/services/encounter_service.py` 的 `get_workspace_snapshot` 返回 `patient_profile`
- `tests/test_patient_profile.py` 5 个测试全过
- **`migrate.py` 已执行**：9 条患者的过敏 / 8 条既往 / 8 条个人史已从 `inquiry_inputs` 迁到 `patients.profile_*`

### 前端 Phase 1 + Round 1.4
- `src/theme/tokens.ts` 设计 tokens 单一来源
- `src/components/shell/AppShell.tsx` + `StatusBar.tsx`（已建，未接入）
- `src/components/common/EmptyState.tsx` + `PatientBar.tsx`
- `LoginPage.tsx` 重写新医疗青主题 + SVG 图标
- `AdminLayout.tsx` 主色换成医疗青
- `domain/medical/types.ts` · `recordTypes.ts` · `inquirySchema.ts` · `index.ts`
- `domain/medical/inquirySchema.test.ts` 7 测试
- 前置 bug 修复：`quick-start` 自动续接、删 ResumeDrawer、初诊/复诊分按钮
- 前置体验：Vitest 配好、主题换医疗青、Noto Sans SC 字体

### 前端 Round 1.5（已完成 2026-04-22）
- `src/store/patientCacheStore.ts` — 多患者档案缓存，LRU 上限 20，不持久化
- `src/store/activeEncounterStore.ts` — 当前接诊指针（patientId/encounterId/visitType 等），挂 persist
- 两个 store 故意解耦：activeEncounter 只存指针，组件用 patientId 去 patientCache 查档案
- 没动 workbenchStore（病历草稿/AI/QC 状态留原处），1.6 起新组件再切换 store 选择器
- `patientCacheStore.test.ts` 9 测试 + `activeEncounterStore.test.ts` 7 测试

### 前端 Round 1.6 — 门诊/急诊侧（已完成 2026-04-22）
- `src/store/encounterIntake.ts` — 集中工具 `applyQuickStartResult` / `applySnapshotResult`，4 处调用点（WorkbenchPage / useInquiryPanel.handleAdmitToInpatient / NewInpatientEncounterModal / useWorkbenchBase.handleResume）已接入
- `src/hooks/usePatientProfileCard.ts` — 从 patientCache 读 profile + 调 PUT /patients/:id/profile，保存成功后回写缓存并同步病历章节
- `src/components/workbench/PatientProfileCard.tsx` — 折叠卡片 8 字段（既往/过敏/个人/家族/月经/婚育/用药/宗教），按 profile 是否有内容决定初始折叠
- `InquiryPanel.tsx` 顶部插入 PatientProfileCard，移除 4 个 profile Form.Item（past_history/allergy_history/personal_history/menstrual_history）
- `useInquiryPanel.ts` 的 allFields/sectionMap/isFemale 已清理 profile 字段
- `useRecordEditor._doGenerate` 发送 payload 时从 patientCache 合并 profile 字段（profile 是权威源，覆盖 inquiry 残留）；`syncGeneratedRecordToInquiry` 不再回写 4 个 profile 字段，避免 AI 单次生成覆盖患者纵向档案
- `encounterIntake.test.ts` 6 测试

测试：后端 pytest 20/20，前端 vitest 34/34（1.6 新增 6），TS 零错误。

### 前端 Round 1.6.2 — 住院端（已完成 2026-04-22）
- `InpatientInquiryPanel.tsx` 顶部插入 PatientProfileCard，与门诊共用同一组件（patient.gender 自动决定月经史显示）
- 删除"二、既往史"、"三、个人史·婚育史·家族史"两个章节标题及其字段
- `SpecialAssessmentSection.tsx` 移除 current_medications、religion_belief 两个 Form.Item（迁入 PatientProfileCard）
- `useInpatientInquiryPanel.ts` 全面清理：form 初始化/onSave inquiryData/changedFields/sectionMap/applyVoiceInquiry 全部移除 8 个 profile 字段；patientGender 状态删除
- `PersonalHistorySection.tsx` 文件**删除**（字段全部迁入卡片，组件失去存在意义）
- 住院 onSave 改用 `setInquiry({...inquiry, ...inquiryData})` 合并写入，避免覆盖其他字段
- AI 生成沿用 useRecordEditor._doGenerate（1.6 已合并 profile），住院 generate 自动获益

测试：vitest 34/34，TS 零错误。

### 前端 Round 1.6.3 — 统一保存按钮 + 语音 profile 路由（已完成 2026-04-22）
基于用户测试反馈："两个保存按钮不合理 + 语音录入的 profile 字段被丢弃"
- **新建 `src/store/patientProfileEditStore.ts`** — 把 PatientProfileCard 的表单态从 React useState 提到 zustand store，挂 persist；含 `loadFromProfile / setField / mergeVoicePatch / save / reset`；同患者+dirty 守护，不被后端推送覆盖未保存草稿
- `usePatientProfileCard.ts` 改为读 store；hook 不再暴露 onSave
- `PatientProfileCard.tsx` 删除内部"保存档案"按钮，改成"档案有未保存修改 — 点下方保存"提示
- `useInquiryPanel.applyVoiceInquiry` + `useInpatientInquiryPanel.applyVoiceInquiry` 增加 `usePatientProfileEditStore.mergeVoicePatch` 调用，把语音 LLM 输出的 profile 字段路由到档案 store
- `InquiryPanel.tsx` + `InpatientInquiryPanel.tsx` 底部按钮变 saveAll：profile dirty 时调 PUT profile + inquiry dirty 时 form.submit()，并发执行；按钮文字按 dirty 组合"保存档案+问诊" / "保存档案" / "保存问诊" / "已保存" / "尚未填写"
- 三个面板（门诊+住院）"保存"按钮 3 态：未填→灰色 disabled / 已保存→绿色 ✓ / 编辑中→蓝色（用 inquirySavedAt>0 判断）
- `patientProfileEditStore.test.ts` 9 测试

**后端**：`prompts_voice.py` VOICE_STRUCTURE_PROMPT_OUTPATIENT 补齐 5 个 profile 字段（marital/menstrual/family/current_medications/religion_belief）+ 字段归属示例（"没有生育过"→marital_history 等）

### 前端 Round 1.6.4 — 刷新数据持久化（已完成 2026-04-22）
基于用户测试反馈："PatientProfileCard 和语音转写刷新后数据丢失"
- **新建 `src/hooks/useEnsureSnapshotHydrated.ts`** — 工作台挂载时检测：有 currentEncounterId 但 patientCache 没数据 → 自动调 `/encounters/:id/workspace` + `applySnapshotResult` 回填
- `WorkbenchPage.tsx` + `InpatientWorkbenchPage.tsx` 挂载时调用 useEnsureSnapshotHydrated
- `patientProfileEditStore` 加 persist：name='medassist-profile-edit'，partialize loadedPatientId/form/isDirty
- **新建 `src/store/voiceTranscriptStore.ts`** — 按 encounterId 索引的语音草稿持久化（transcript/summary/speakerDialogue/transcriptId/lastAnalyzedTranscript），LRU 上限 10 个 encounter
- `useVoiceInputCard.ts` 重构：mount 时双层恢复（先 store 瞬时恢复 → 再 /workspace 拉后端最新覆盖）；state 变化自动 sync 到 store；clearTranscript 同步调 store.clearForEncounter
- **守护时序 bug**：mount 时 React 初始空 state 会被 sync effect 写入 store 覆盖刚 persist 的内容 → sync effect 加守护"要写入的全空 + store 已有内容则跳过"；restore 的后端覆盖也加非空守护

测试：vitest 43/43，TS 零错误。

## ⚠️ 待用户浏览器验证（换电脑后接力的核心）

用户已测过 1.6+1.6.2 部分场景（截图反馈），1.6.3+1.6.4 修复后**未充分验证**。新会话开始时**先问用户最新测试反馈**，再决定下一步。

## ⏭️ 下一步（按顺序）

1. **等用户浏览器验证 1.6.3+1.6.4 修复**（语音 profile 路由 / 统一保存按钮 / 刷新数据持久化）
2. **Round 1.7** — 复诊打开患者自动带入档案的端到端验证（门诊+住院全链路）
3. **Round 2** — 住院领域层：`domain/inpatient/timelineBuilder.ts` + `recordRules.ts` + 路由 `/inpatient/patient/:pid/r/:rid` + 时间轴导航组件 + 重写住院工作台
4. **Phase 2** — 全局快捷键 + 状态栏接入 + AppShell 迁移工作台 + 问诊分组折叠 + AI 建议反馈
5. **Phase 3** — 管理后台迁移到 AppShell
6. **Phase 4** — PACS 进度指示器 + 深色模式

## ⚠️ 1.6 + 1.6.2 浏览器测试要点（用户测时关注）

**门诊/急诊**
- **初诊新患者**：PatientProfileCard 默认展开（profile 空）→填过敏史→保存→刷新页面档案保留
- **复诊已有患者**：卡片默认折叠+显示"已填：..."摘要→展开能看到上次档案
- **改档案同步章节**：病历已生成时，改过敏史并保存→【过敏史】章节被同步替换
- **AI 生成不退化**：点生成→后端 prompt 拿到完整 profile（来自 patientCache 合并）→生成病历含【既往史】【过敏史】等章节
- **多患者切换**：A 患者档案展开编辑→不保存切换到 B→切回 A→看到 A 的最新值（patientCache LRU 命中）

**住院**
- **入院新登记**：PatientProfileCard 在住院问诊面板顶部出现，与门诊同一卡片→填档案→保存
- **专项评估精简**：检查"二、专项评估"区块只剩 5 个字段（康复/疼痛/VTE/营养/心理）
- **章节顺序**："一、主诉与现病史 → 二、专项评估 → 三、体格检查与辅助检查 → 四、入院诊断"
- **入院记录生成**：profile 字段合并进 prompt → 生成的入院记录含完整既往史/过敏史/婚育史/月经史等

**急诊→住院转入**
- 在急诊填档案→点"转住院"→住院页打开→PatientProfileCard 自动带入急诊填的过敏史/既往史等
- 住院 InpatientInquiryPanel 不再渲染这些字段，避免重复编辑

## 🔑 关键约束

- 门诊/急诊只有 1 个 `WorkbenchPage` + 13 行壳 `EmergencyWorkbenchPage`，别再拆
- 所有颜色从 `src/theme/tokens.ts` 读取，禁止硬编码
- 续接诊功能已删（`ResumeDrawer`），不要复活
- 复诊自动续接：`quick-start` 已检测 `in_progress` 接诊，不要重建

## 新会话启动

用户重开窗口时只需说"继续"，先读此文件 + `TodoWrite` 查当前任务、读 `src/domain/medical/` 当前状态、读相关 store 文件，然后从"下一步"的下一个未完成项继续。

## 🖥️ 新电脑接力 Checklist（2026-04-22 新增）

### 必做
1. `git clone https://gitee.com/Zhang___Zheng/hospital-ai-assistant.git`（或 GitHub URL）
2. `cd frontend && npm install`（约 1-2 分钟）
3. `cd ../backend && python -m venv venv && venv\Scripts\activate && pip install -r requirements.txt`
4. 启服务：`scripts/start-backend.bat` + `scripts/start-frontend.bat`
5. 跟新电脑的 Claude 说："**读 docs/REFACTOR_ROADMAP.md，从下一步未完成项继续**"

### 选做（让 Claude 知道你的工作偏好）
旧电脑 `C:\Users\<旧用户名>\.claude\projects\d--Code-hospital-ai-assistant\memory\` 整个目录复制到新电脑同样位置。这里面是 13 条 user/feedback/project/reference memory（如下载路径偏好/不用 MCP 浏览器/查 bug 看 error.log/单文件行数控制等）。**不复制的话新电脑的 Claude 不知道你的协作习惯**，每次会重新踩坑。

### 浏览器测试上下文（localStorage）
旧电脑浏览器里的患者档案草稿/语音转写都存在 `localStorage`，新电脑浏览器里是空的——这正常。后端保存过的数据（已点过"保存档案"/上传过的语音）能从 snapshot 拉回来。

## 📋 待用户浏览器验证项（1.6.3 + 1.6.4 修复后）

新电脑接力做的第一件事——验证以下场景，反馈结果：

1. **语音录入 profile 字段路由**：录一段含"颈椎病/无过敏史/未生育/无宗教信仰"的话，点"重新分析"，应看到这些词分别填进 PatientProfileCard 的对应字段（既往史/过敏史/婚育史/宗教信仰）+ 弹"已将 N 项档案信息填入"提示
2. **统一保存按钮**：底部按钮文字应根据 dirty 组合显示"保存档案+问诊"/"保存档案"/"保存问诊"/"已保存"/"尚未填写"，一次点击同时 PUT profile 和 inquiry
3. **刷新数据保留**：填档案/录语音转写后**不点保存就刷新**，PatientProfileCard 草稿应该还在，语音转写文本也还在
4. **三态按钮**：刚进新接诊（未填）按钮应是灰色"尚未填写"（disabled），保存后变绿色"已保存"，编辑中变蓝色

**反馈方式**：第几条不对？期望什么？实际什么？浏览器 Console (F12) 报错？后端 `logs/error.log` 有 WARNING 以上吗？

## 🔄 本次会话（2026-04-22）git 提交链 — 新电脑接力时可参考

`7ce135e` (Round 1 全栈重构) → `afcfade` (merge github PR 历史) → `1a702b3` (后端 ruff lint 修复) → `fd56e8a` (lock 跨平台 attempt 1) → `0fc8861` (lock A 方案重装) → `9dbf3ea` (pytest pythonpath + npm install) → `b6fd4a6` (WardView purity + backend env) → `b27a216` (YAML 引号修复) → `82e14a8` (database.py SQLite 兼容) → **GitHub PR #5 merged 到 main**

CI 已全绿，Gitee + GitHub 双 remote 同步。
