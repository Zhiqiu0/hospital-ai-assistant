# 数据库设计文档

> 数据库：PostgreSQL 16 | 更新日期：2026-03-25

---

## 一、表结构总览

```
departments          科室表
users                用户表（医生/管理员）
patients             患者表
encounters           就诊记录表
inquiry_inputs       问诊输入表
medical_records      病历主表
record_versions      病历版本表
ai_tasks             AI任务表
inquiry_suggestions  问诊建议表
exam_suggestions     检查建议表
qc_issues            质控问题表
qc_rules             质控规则配置表
prompt_templates     Prompt模板表
model_configs        模型配置表
record_templates     病历模板表
audit_logs           操作审计日志表
voice_records        语音录入记录表
lab_reports          检验报告上传表
imaging_studies      影像检查表（PACS）
imaging_reports      影像报告表（PACS）
revoked_tokens       已吊销 Token 表（Logout 黑名单）
```

---

## 二、ER 关系说明

```
departments  ←─────── users
                         │
patients ───────── encounters ───── inquiry_inputs
    │                    │
    │               medical_records
    │                    │
    │               record_versions ←── ai_tasks
    │                                       │
    │                               inquiry_suggestions
    │                               exam_suggestions
    │                               qc_issues
    │
    ├── lab_reports         （检验报告上传，OCR 解析）
    └── imaging_studies ─── imaging_reports   （PACS 影像）

voice_records              （语音录入，关联 encounter）
audit_logs                 （操作审计，关联 user/patient）
revoked_tokens             （Logout JWT 黑名单）
```

---

## 三、完整建表 SQL

```sql
-- 启用 UUID 扩展
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. 科室表
-- ============================================================
CREATE TABLE departments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(100) NOT NULL,
    code          VARCHAR(50) UNIQUE NOT NULL,        -- 科室编码
    parent_id     UUID REFERENCES departments(id),    -- 支持科室层级
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE departments IS '科室表';
COMMENT ON COLUMN departments.code IS '科室编码，如 NEIKE、WAIKE';

-- ============================================================
-- 2. 用户表（医生 / 管理员）
-- ============================================================
CREATE TABLE users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username       VARCHAR(50) UNIQUE NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    real_name      VARCHAR(50) NOT NULL,
    role           VARCHAR(20) NOT NULL
                   CHECK (role IN ('super_admin','hospital_admin','dept_admin','doctor','qc_viewer')),
    department_id  UUID REFERENCES departments(id),
    employee_no    VARCHAR(50),                       -- 工号
    phone          VARCHAR(20),
    email          VARCHAR(100),
    is_active      BOOLEAN DEFAULT TRUE,
    last_login_at  TIMESTAMP,
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE users IS '用户表，包含医生和各级管理员';
COMMENT ON COLUMN users.role IS 'super_admin/hospital_admin/dept_admin/doctor/radiologist/qc_viewer';

-- ============================================================
-- 3. 患者表
-- ============================================================
CREATE TABLE patients (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_no    VARCHAR(50) UNIQUE,                 -- HIS就诊号/住院号
    name          VARCHAR(50) NOT NULL,
    gender        VARCHAR(10) CHECK (gender IN ('male','female','unknown')),
    birth_date    DATE,
    id_card       VARCHAR(20),                        -- 身份证号（加密存储）
    phone         VARCHAR(20),
    address       TEXT,
    is_from_his   BOOLEAN DEFAULT FALSE,              -- 是否从HIS同步
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE patients IS '患者基础信息表';
COMMENT ON COLUMN patients.id_card IS '身份证号，生产环境需加密存储';

-- ============================================================
-- 4. 就诊记录表（一次接诊）
-- ============================================================
CREATE TABLE encounters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID NOT NULL REFERENCES patients(id),
    doctor_id       UUID NOT NULL REFERENCES users(id),
    department_id   UUID REFERENCES departments(id),
    visit_type      VARCHAR(20) NOT NULL
                    CHECK (visit_type IN ('outpatient','inpatient','emergency')),
    visit_no        VARCHAR(50),                      -- HIS就诊编号
    is_first_visit  BOOLEAN DEFAULT TRUE,             -- 初诊/复诊
    status          VARCHAR(20) DEFAULT 'in_progress'
                    CHECK (status IN ('in_progress','completed','cancelled')),
    chief_complaint_brief VARCHAR(200),               -- 主诉摘要（快速检索用）
    visited_at      TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE encounters IS '就诊记录，一次接诊对应一条记录';

-- ============================================================
-- 5. 问诊输入表（医生录入内容）
-- ============================================================
CREATE TABLE inquiry_inputs (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id              UUID NOT NULL REFERENCES encounters(id),
    chief_complaint           TEXT,                   -- 主诉
    history_present_illness   TEXT,                   -- 现病史
    past_history              TEXT,                   -- 既往史
    allergy_history           TEXT,                   -- 过敏史
    personal_history          TEXT,                   -- 个人史
    physical_exam             TEXT,                   -- 体格检查
    initial_impression        TEXT,                   -- 初步印象
    version                   INTEGER DEFAULT 1,      -- 输入版本（每次保存递增）
    created_at                TIMESTAMP DEFAULT NOW(),
    updated_at                TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE inquiry_inputs IS '医生问诊录入内容，保留每次修改版本';

-- ============================================================
-- 6. 病历主表
-- ============================================================
CREATE TABLE medical_records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id     UUID NOT NULL REFERENCES encounters(id),
    record_type      VARCHAR(30) NOT NULL
                     CHECK (record_type IN ('outpatient','admission_note','first_course_record')),
    status           VARCHAR(20) DEFAULT 'draft'
                     CHECK (status IN (
                         'draft',          -- 草稿未生成
                         'generating',     -- AI生成中
                         'generated',      -- AI生成完成
                         'editing',        -- 医生编辑中
                         'qc_pending',     -- 质控检查中
                         'qc_done',        -- 质控完成
                         'submitted'       -- 已提交
                     )),
    current_version  INTEGER DEFAULT 0,   -- 当前使用版本号
    submitted_at     TIMESTAMP,
    created_at       TIMESTAMP DEFAULT NOW(),
    updated_at       TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE medical_records IS '病历主表，一次就诊可有多种类型病历';
COMMENT ON COLUMN medical_records.status IS '病历状态流转：draft→generating→generated→editing→qc_pending→qc_done→submitted';

-- ============================================================
-- 7. 病历版本表（每次生成/修改都保存版本）
-- ============================================================
CREATE TABLE record_versions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    medical_record_id UUID NOT NULL REFERENCES medical_records(id),
    version_no        INTEGER NOT NULL,
    content           JSONB NOT NULL,                 -- 结构化病历内容
    source            VARCHAR(20) NOT NULL
                      CHECK (source IN (
                          'ai_generated',   -- AI初次生成
                          'ai_continued',   -- AI续写
                          'ai_polished',    -- AI润色
                          'ai_completed',   -- AI补全
                          'doctor_edited'   -- 医生手工编辑
                      )),
    triggered_by      UUID REFERENCES users(id),
    ai_task_id        UUID,                           -- 关联AI任务
    created_at        TIMESTAMP DEFAULT NOW(),
    UNIQUE (medical_record_id, version_no)
);

COMMENT ON TABLE record_versions IS '病历版本历史，支持完整追溯';
COMMENT ON COLUMN record_versions.content IS 'JSONB结构，包含chief_complaint/history_present_illness等字段';

-- ============================================================
-- 8. AI 任务表
-- ============================================================
CREATE TABLE ai_tasks (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id       UUID REFERENCES encounters(id),
    medical_record_id  UUID REFERENCES medical_records(id),
    task_type          VARCHAR(30) NOT NULL
                       CHECK (task_type IN (
                           'inquiry_suggestion',  -- 问诊追问建议
                           'record_generate',     -- 病历生成
                           'record_continue',     -- 续写
                           'record_polish',       -- 润色
                           'record_complete',     -- 补全
                           'exam_suggestion',     -- 检查建议
                           'qc_scan'              -- 质控扫描
                       )),
    status             VARCHAR(20) DEFAULT 'pending'
                       CHECK (status IN ('pending','running','success','failed','cancelled')),
    input_snapshot     JSONB,                         -- 输入内容快照（审计用）
    output_result      JSONB,                         -- 模型输出原始结果
    model_name         VARCHAR(50),                   -- 使用的模型
    prompt_version     VARCHAR(20),                   -- Prompt版本号
    token_input        INTEGER,                       -- 输入token数
    token_output       INTEGER,                       -- 输出token数
    duration_ms        INTEGER,                       -- 耗时（毫秒）
    error_message      TEXT,
    created_at         TIMESTAMP DEFAULT NOW(),
    completed_at       TIMESTAMP
);

COMMENT ON TABLE ai_tasks IS '每次AI调用记录，用于审计、调优和成本统计';

-- ============================================================
-- 9. 问诊建议表
-- ============================================================
CREATE TABLE inquiry_suggestions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ai_task_id    UUID NOT NULL REFERENCES ai_tasks(id),
    encounter_id  UUID NOT NULL REFERENCES encounters(id),
    priority      VARCHAR(10) NOT NULL CHECK (priority IN ('high','medium','low')),
    category      VARCHAR(50),                        -- 建议类别（症状/病史/伴随症状等）
    suggestion    TEXT NOT NULL,                      -- 追问内容
    reason        TEXT,                               -- 建议原因
    is_red_flag   BOOLEAN DEFAULT FALSE,              -- 是否危险信号
    status        VARCHAR(20) DEFAULT 'pending'
                  CHECK (status IN ('pending','asked','ignored','inserted')),
    source        VARCHAR(10) DEFAULT 'llm' CHECK (source IN ('rule','llm')),
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE inquiry_suggestions IS '问诊追问建议，医生可标记已问/忽略/插入';

-- ============================================================
-- 10. 检查建议表
-- ============================================================
CREATE TABLE exam_suggestions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ai_task_id    UUID NOT NULL REFERENCES ai_tasks(id),
    encounter_id  UUID NOT NULL REFERENCES encounters(id),
    category      VARCHAR(20) CHECK (category IN ('basic','differential','high_risk')),
    exam_name     VARCHAR(100) NOT NULL,              -- 检查项目名称
    reason        TEXT,                               -- 建议原因
    status        VARCHAR(20) DEFAULT 'pending'
                  CHECK (status IN ('pending','adopted','ignored')),
    created_at    TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE exam_suggestions IS '检查建议，仅供参考不自动下单';

-- ============================================================
-- 11. 质控问题表
-- ============================================================
CREATE TABLE qc_issues (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ai_task_id         UUID NOT NULL REFERENCES ai_tasks(id),
    medical_record_id  UUID NOT NULL REFERENCES medical_records(id),
    record_version_no  INTEGER,                       -- 对应的病历版本
    issue_type         VARCHAR(30) NOT NULL
                       CHECK (issue_type IN (
                           'completeness',       -- 完整性
                           'standardization',    -- 规范性
                           'logic_consistency',  -- 逻辑一致性
                           'insurance_risk'      -- 医保风险
                       )),
    risk_level         VARCHAR(10) NOT NULL CHECK (risk_level IN ('high','medium','low')),
    field_name         VARCHAR(50),                   -- 问题对应字段（如chief_complaint）
    issue_description  TEXT NOT NULL,                 -- 问题说明
    suggestion         TEXT,                          -- 修改建议
    status             VARCHAR(20) DEFAULT 'open'
                       CHECK (status IN ('open','resolved','ignored')),
    source             VARCHAR(10) DEFAULT 'rule' CHECK (source IN ('rule','llm','mixed')),
    resolved_at        TIMESTAMP,
    created_at         TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE qc_issues IS '质控问题列表，按高/中/低风险分级展示';

-- ============================================================
-- 12. 质控规则配置表
-- ============================================================
CREATE TABLE qc_rules (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_code                VARCHAR(50) UNIQUE NOT NULL,
    rule_name                VARCHAR(100) NOT NULL,
    rule_type                VARCHAR(30) NOT NULL
                             CHECK (rule_type IN ('completeness','standardization','logic_consistency','insurance_risk')),
    applicable_record_types  TEXT[] DEFAULT ARRAY['outpatient','admission_note','first_course_record'],
    applicable_departments   TEXT[],                  -- NULL 表示全科室适用
    condition_config         JSONB,                   -- 规则触发条件（JSON配置）
    risk_level               VARCHAR(10) NOT NULL CHECK (risk_level IN ('high','medium','low')),
    is_blocking              BOOLEAN DEFAULT FALSE,   -- 是否强制拦截提交
    issue_template           TEXT,                    -- 问题描述模板
    suggestion_template      TEXT,                    -- 修改建议模板
    source                   VARCHAR(10) DEFAULT 'rule' CHECK (source IN ('rule','llm','mixed')),
    is_active                BOOLEAN DEFAULT TRUE,
    created_at               TIMESTAMP DEFAULT NOW(),
    updated_at               TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE qc_rules IS '质控规则库，支持后台可视化配置';

-- ============================================================
-- 13. Prompt 模板表
-- ============================================================
CREATE TABLE prompt_templates (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_key    VARCHAR(50) UNIQUE NOT NULL,
    scene         VARCHAR(30) NOT NULL
                  CHECK (scene IN (
                      'inquiry_suggestion',
                      'record_generate',
                      'record_continue',
                      'record_polish',
                      'record_complete',
                      'exam_suggestion',
                      'qc_standardization',
                      'qc_logic',
                      'qc_insurance'
                  )),
    record_type   VARCHAR(30),                        -- NULL 表示适用所有类型
    version       VARCHAR(20) NOT NULL,               -- 版本号，如 v1.0
    template      TEXT NOT NULL,                      -- Prompt 模板内容
    output_schema JSONB,                              -- 期望的输出JSON格式定义
    model_name    VARCHAR(50),                        -- 指定模型，NULL 使用默认
    is_active     BOOLEAN DEFAULT TRUE,
    created_by    UUID REFERENCES users(id),
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE prompt_templates IS 'Prompt模板，支持版本管理和按场景路由';

-- ============================================================
-- 14. 模型配置表
-- ============================================================
CREATE TABLE model_configs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key      VARCHAR(50) UNIQUE NOT NULL,
    provider        VARCHAR(30) NOT NULL,             -- deepseek/openai/anthropic/qianwen
    model_name      VARCHAR(50) NOT NULL,
    base_url        VARCHAR(200),
    scene           VARCHAR(30),                      -- 适用场景，NULL 为默认配置
    max_tokens      INTEGER DEFAULT 4096,
    temperature     FLOAT DEFAULT 0.3,
    is_active       BOOLEAN DEFAULT TRUE,
    is_default      BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE model_configs IS '模型配置，API Key通过环境变量管理不存库';

-- ============================================================
-- 15. 病历模板表
-- ============================================================
CREATE TABLE record_templates (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(100) NOT NULL,
    record_type   VARCHAR(30) NOT NULL
                  CHECK (record_type IN ('outpatient','admission_note','first_course_record')),
    department_id UUID REFERENCES departments(id),    -- NULL 表示通用模板
    structure     JSONB NOT NULL,                     -- 模板结构定义（各字段及顺序）
    is_active     BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT NOW(),
    updated_at    TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE record_templates IS '病历结构模板，支持按科室定制';

-- ============================================================
-- 16. 操作日志表（审计）
-- ============================================================
CREATE TABLE operation_logs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID REFERENCES users(id),
    action         VARCHAR(50) NOT NULL,              -- 操作类型
    resource_type  VARCHAR(30),                       -- 操作资源类型
    resource_id    UUID,                              -- 操作资源ID
    patient_id     UUID REFERENCES patients(id),      -- 涉及患者（用于隐私审计）
    ip_address     VARCHAR(50),
    request_data   JSONB,                             -- 请求摘要
    response_code  INTEGER,
    created_at     TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE operation_logs IS '操作审计日志，记录谁在何时操作了什么';

-- ============================================================
-- 索引
-- ============================================================
CREATE INDEX idx_users_department ON users(department_id);
CREATE INDEX idx_encounters_patient ON encounters(patient_id);
CREATE INDEX idx_encounters_doctor ON encounters(doctor_id);
CREATE INDEX idx_encounters_status ON encounters(status);
CREATE INDEX idx_medical_records_encounter ON medical_records(encounter_id);
CREATE INDEX idx_medical_records_status ON medical_records(status);
CREATE INDEX idx_record_versions_record ON record_versions(medical_record_id);
CREATE INDEX idx_ai_tasks_encounter ON ai_tasks(encounter_id);
CREATE INDEX idx_ai_tasks_status ON ai_tasks(status);
CREATE INDEX idx_ai_tasks_type ON ai_tasks(task_type);
CREATE INDEX idx_inquiry_suggestions_encounter ON inquiry_suggestions(encounter_id);
CREATE INDEX idx_qc_issues_record ON qc_issues(medical_record_id);
CREATE INDEX idx_qc_issues_status ON qc_issues(status);
CREATE INDEX idx_operation_logs_user ON operation_logs(user_id);
CREATE INDEX idx_operation_logs_patient ON operation_logs(patient_id);
CREATE INDEX idx_operation_logs_created ON operation_logs(created_at);
```

---

## 四、关键字段说明

### record_versions.content 结构（JSONB）

```json
{
  "chief_complaint": "发热3天，体温最高39.5℃",
  "history_present_illness": "患者3天前无明显诱因出现发热...",
  "past_history": "否认高血压、糖尿病史",
  "allergy_history": "青霉素过敏",
  "personal_history": "无吸烟饮酒史",
  "physical_exam": {
    "vital_signs": "T 38.8℃ P 92次/分 R 20次/分 BP 120/80mmHg",
    "general": "神志清楚，急性病容",
    "chest": "双肺呼吸音粗",
    "abdomen": "腹软，无压痛"
  },
  "initial_diagnosis": "急性上呼吸道感染"
}
```

### qc_rules.condition_config 结构（JSONB）

```json
{
  "type": "field_empty",
  "field": "chief_complaint",
  "max_length": 100,
  "min_length": 5
}
```

---

## 五、初始数据说明

系统启动时需插入：
1. 默认超级管理员账号
2. 默认质控规则（完整性规则约15条）
3. 默认Prompt模板（各场景各1条）
4. 默认模型配置（DeepSeek-V3）

详见 `scripts/init_data.sql`

---

## 六、后续新增表（2026-03-25）

```sql
-- ============================================================
-- 17. 语音录入记录表
-- ============================================================
CREATE TABLE voice_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id    UUID REFERENCES encounters(id),
    doctor_id       UUID NOT NULL REFERENCES users(id),
    audio_file_path VARCHAR(300),                       -- 录音文件相对路径
    transcript      TEXT,                              -- ASR 转写文本
    structured      JSONB,                             -- AI 结构化后的问诊字段
    duration_sec    INTEGER,                           -- 录音时长（秒）
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 18. 检验报告上传表
-- ============================================================
CREATE TABLE lab_reports (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id      UUID REFERENCES encounters(id),
    patient_id        UUID NOT NULL REFERENCES patients(id),
    uploader_id       UUID NOT NULL REFERENCES users(id),
    original_filename VARCHAR(255),                    -- 原始文件名
    file_path         VARCHAR(500),                    -- 相对存储路径
    file_type         VARCHAR(10),                     -- pdf / jpg / png
    ocr_text          TEXT,                            -- OCR 解析全文
    report_type       VARCHAR(100),                    -- 解析出的报告类型
    created_at        TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 19. 影像检查表（PACS）
-- ============================================================
CREATE TABLE imaging_studies (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id         UUID NOT NULL REFERENCES patients(id),
    uploaded_by        UUID NOT NULL REFERENCES users(id),
    modality           VARCHAR(20),                    -- CT / MRI / XR 等
    body_part          VARCHAR(50),
    series_description VARCHAR(200),
    total_frames       INTEGER DEFAULT 0,
    storage_dir        TEXT,                           -- DICOM 文件存储目录
    status             VARCHAR(20) DEFAULT 'pending'
                       CHECK (status IN ('pending','analyzed','published')),
    created_at         TIMESTAMP DEFAULT NOW(),
    updated_at         TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 20. 影像报告表（PACS）
-- ============================================================
CREATE TABLE imaging_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    study_id        UUID NOT NULL REFERENCES imaging_studies(id),
    radiologist_id  UUID REFERENCES users(id),
    selected_frames TEXT[],                            -- 选中分析的帧文件名
    ai_analysis     TEXT,                              -- AI 分析结果（Markdown）
    final_report    TEXT,                              -- 医生审核后的最终报告
    is_published    BOOLEAN DEFAULT FALSE,
    published_at    TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 21. 审计日志表
-- ============================================================
CREATE TABLE audit_logs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID REFERENCES users(id),
    user_name      VARCHAR(50),
    user_role      VARCHAR(30),
    action         VARCHAR(50) NOT NULL,
    resource_type  VARCHAR(30),
    resource_id    VARCHAR(100),
    detail         TEXT,
    ip_address     VARCHAR(50),
    status         VARCHAR(20) DEFAULT 'success',
    created_at     TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- 22. 已吊销 Token 表（Logout 黑名单）
-- ============================================================
CREATE TABLE revoked_tokens (
    jti         VARCHAR(36) PRIMARY KEY,               -- JWT ID (uuid)
    expires_at  TIMESTAMP NOT NULL,                    -- Token 过期时间
    revoked_at  TIMESTAMP DEFAULT NOW()
);
```
