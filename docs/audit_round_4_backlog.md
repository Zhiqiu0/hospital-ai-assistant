# 第 4 轮架构审计 Backlog

> 产出日期：2026-04-25
> 来源：综合代码 review（Skill: code-review）
> 状态约定：`[ ]` 待办 / `[x]` 完成 / `[~]` 进行中 / `[!]` 阻塞

按"打地基"优先级三档：🔴 安全/合规硬伤 → 🟡 影响下一步功能开发 → 🟢 顺手清理

---

## 🔴 严重：必须立即处理（共 3 项）

### S1. PACS 影像端点权限漏洞（PHI 泄露）
- **文件**：`backend/app/api/v1/pacs.py`
- **问题**：
  - L333-378 `/{study_id}/thumbnail/{filename}` **无任何鉴权**
  - L383-399 `/{study_id}/dicom/{filename}` **无任何鉴权**
  - L303-328 `/{study_id}/frames` 仅要求登录，没校验跨患者权限
- **根因**：PACS 路由后期加，没接入 `core/authz.py` 的统一鉴权模式
- **修复**：3 个端点统一加 `Depends(get_current_user)` + `await assert_patient_access(db, study.patient_id, current_user)`
- **验收**：未登录访问返回 401；登录但跨患者访问返回 403

### S2. publish_report 覆盖真实分析人（审计断链）
- **文件**：`backend/app/api/v1/pacs.py:539-562` + `backend/app/models/imaging.py`
- **问题**：发布时 `report.radiologist_id = current_user.id` 会覆盖原分析人；A 分析、B 发布会让审计变成"B 全程负责"
- **修复**：
  - `ImagingReport` 加 `published_by: ForeignKey("users.id")` 字段
  - `schema_compat.py` 加 `ALTER TABLE ADD COLUMN IF NOT EXISTS published_by`
  - `publish_report` 不再修改 `radiologist_id`，改写 `published_by = current_user.id`
- **验收**：分析→发布跨人场景下，`radiologist_id` 不变，`published_by` 记录发布人

### S3. 管理员特权操作零审计（合规硬伤）
- **文件**：`backend/app/api/v1/admin/*.py`（9 个文件全部）+ 新建 `backend/app/core/audit_dep.py`
- **问题**：用户增删改、改 Prompt、改质控规则、改模型配置、删患者……全部**没有 log_action 调用**
- **根因**：靠人工每端点写 audit 必漏，缺机制
- **修复**：
  - 新建 `audit_admin_action` 依赖（FastAPI Dependency），自动捕获 method/path/user/status，请求结束后写 audit_logs
  - 在 `api/v1/__init__.py` 的所有 `admin/*` `include_router` 里统一加 `dependencies=[Depends(audit_admin_action)]`
- **验收**：调用任意 admin 路由后，audit_logs 表新增 1 条 action=`admin:METHOD:/admin/xxx` 记录

---

## 🟡 重要：影响下一步功能开发（共 6 项）

### M1. workbenchStore 上帝对象拆分
- **文件**：`frontend/src/store/workbenchStore.ts`（415 行）
- **问题**：9 类职责混一个 store；`reset()` 列 19 字段易漏；持久化范围过大可能撞 5MB；切换接诊状态污染（已经修过 examSuggestions 的 bug 是证据）
- **拆分方向**：
  - `inquiryStore`（问诊数据，按 visit_type 分子结构）
  - `recordStore`（病历内容、版本、签发态）
  - `qcStore`（质控状态）
  - `aiSuggestionStore`（追问/检查/诊断建议）
  - 复用现有 `activeEncounterStore` 作为 currentEncounterId 唯一来源
- **关键设计**：让各 store 订阅 currentEncounterId 变化自清，不再手写 reset 逐字段
- **验收**：切换接诊后所有衍生状态自动清；不再有"漏 reset 一个字段"的可能

### M2. medical_record_service 的 N+1 查询
- **文件**：`backend/app/services/medical_record_service.py:201-353`
- **问题**：
  - `list_by_doctor` / `list_by_patient` 80% 重复
  - 每页 20 条 = 40 次额外查询（每 record 单独查 RecordVersion + 单独 count visit_sequence）
  - 函数体内 `from sqlalchemy import func as _func` 是清洗不彻底的重构遗留
- **修复**：抽 `_paginate_records(filter_clause, page, page_size)` 共用方法；用 window function `row_number()` 一次取每个 record 的最新 version；用 `func.count().over(...)` 算 visit_sequence
- **验收**：单页加载 SQL 查询 ≤ 3 次（count + 主查询 + 全量 RecordVersion）

### M3. encounter_service.get_workspace_snapshot 拆解
- **文件**：`backend/app/services/encounter_service.py:126-322`
- **问题**：单方法 200+ 行；4 个独立 await 查询；内容三态解析 inline；40+ 字段手工 `or ""` 拼装；records 循环 N+1
- **修复**：
  - 抽 `_parse_record_content(content) -> str` 工具方法（覆盖 dict-with-text / 结构化 dict / 纯字符串三态）
  - inquiry 字典用 Pydantic Schema 序列化，不再手工 `or ""`
  - records + 最新 version 用一次 join 查回
- **验收**：方法主体 ≤ 50 行；snapshot 总查询次数 ≤ 5 次

### M4. 路由命名 + 文件分布混乱
- **文件**：`backend/app/api/v1/`
- **问题**：7 个 ai 开头文件平铺；`ai_voice_stream` 不在 `ai.py` 聚合内；`pacs.py` 716 行单文件
- **修复**（不急于一次到位，下一轮做 pacs_service 时同步）：
  - `api/v1/ai/` 子目录聚合 ai 系列
  - `api/v1/pacs/` 子目录拆 upload/viewer/analyze/report
- **验收**：v1/__init__.py 顶层 import 行数减少 ≥ 50%

### M5. 后端测试覆盖盲区
- **现状**：6/13 service 有测试；API 层 0 测试
- **优先补**（按业务关键度）：
  - `encounter_service.get_workspace_snapshot`（最复杂、最易因 schema 变化炸）
  - `medical_record_service.quick_save`（并发锁 + 跨表事务）
  - `audit_service.log_action`（"静默失败"行为没测试，可能哪天悄悄全失败也不知道）
  - `services/rule_engine/*`（病历质控规则，业务核心）
- **验收**：测试用例数 ≥ 50；rule_engine 至少覆盖完整性/医保两大类

### M6. 前端超长文件拆分
- **超规范文件**：见 review 报告 M6 表格（15 个组件/页面/hook 超限）
- **优先级**：
  - 配合 M1 一起拆 InquiryPanel.tsx（477 行，业务已抽 hook，剩 JSX 也需切 section）
  - StatsPage.tsx（680 行）→ overview/token/usage/qc 4 个独立页/Tab
  - useRecordEditor.ts（470 行）的 SSE 流处理抽到 `services/streamSSE.ts`，与 voiceStream.ts 合并
- **验收**：组件 ≤ 300 行 / 页面 ≤ 400 行 / 服务 ≤ 250 行 全部达标

---

## 🟢 改进：路过时顺手清（共 7 项）

### G1. 删孤儿组件 ResumeDrawer
- **文件**：`frontend/src/components/workbench/ResumeDrawer.tsx`（153 行）
- **现状**：全 frontend 0 代码引用，仅 WorkbenchPage.tsx 注释里提名字
- **修复**：直接删

### G2. PACS analyze_study / analyze_image 重复
- **文件**：`backend/app/api/v1/pacs.py:408 / 609`
- **修复**：抽 `_call_qwen_vl(images, prompt) -> str`；prompt 移到 `services/ai/prompts_*.py` 与项目其他 AI prompt 集中管理

### G3. PACS 7-zip 全盘搜索
- **文件**：`backend/app/api/v1/pacs.py:220-233`
- **问题**：每次上传 RAR 触发全盘 glob，慢且泄露目录结构
- **修复**：startup 时检测一次，未装 fail-fast；不在请求路径里搜

### G4. PACS save_report / publish_report 合并
- **文件**：`backend/app/api/v1/pacs.py:521-562`
- **修复**：合并为 `save_report(publish: bool = False)`

### G5. PACS DCM 临时文件泄露
- **文件**：`backend/app/api/v1/pacs.py:631-635`
- **问题**：`os.unlink(tmp_path)` 在异常时不会执行
- **修复**：try/finally 或改用 `delete=True` + 流式

### G6. 角色集合定义漂移
- **文件**：`backend/app/api/v1/pacs.py:58` vs `backend/app/core/authz.py:26-27`
- **问题**：pacs.py 自己定义 `PRIVILEGED_ROLES = {"radiologist", "admin", "super_admin"}` 与 authz.py 的 `ADMIN_ROLES` 值不一致
- **修复**：删除 pacs.py 自定义集合，全部从 `authz` 单一来源 import

### G8. 测试默认连接开发 PG（隔离漏洞）
- **现象**：`audit_service.log_action` 用模块级 `AsyncSessionLocal`，pytest 跑起来时也走的是 dev PostgreSQL（在 admin 审计测试里观察到 INSERT 用了 PG 的 `now()` 函数）
- **根因**：`backend/app/database.py` 里的 `AsyncSessionLocal` 在 import 时就绑定到 `settings.database_url`，conftest.py 没有全局覆盖
- **风险**：测试用例若不慎 commit 到生产/开发库就污染数据；且测试结果取决于本地库的当前状态，不可重现
- **修复**：在 `tests/conftest.py` 顶部用 monkeypatch 把 `app.database.AsyncSessionLocal` 替换成测试 SQLite session factory；或者在加载 settings 前注入 `DATABASE_URL=sqlite+aiosqlite:///:memory:` 环境变量
- **验收**：把本地 PG 服务停掉，pytest 仍能 100% 跑通

### G7. 修复历史不应写代码注释
- **文件**：示例 `frontend/src/store/workbenchStore.ts:393`、`backend/app/services/encounter_service.py:105-107`
- **约定**：注释只解释"为什么"，"什么时候改的、谁改的、修了什么 bug"属于 git commit message
- **修复**：路过时顺手把 "Bug 修复 2026-04-25" 这类注释删掉

---

## 收敛节奏

- 每次只挑 1-3 项做完整闭环：**改 → 跑测试 → 本地点一遍 → 划掉 → 下一项**
- 改一项发现新问题：跟当前强相关 → 顺手修；无关 → 加进本 backlog
- 不再做全局 review，除非批量做完一轮想看效果或上线前
- 所有项做完前提：每改完跑 `pytest -q` 全绿（当前 29 用例 1.9s）
