-- 清空业务数据，保留用户、配置、权限
-- 执行顺序：先子表，再父表（避免外键冲突）
-- 用法：psql -U <user> -d <dbname> -f clear_business_data.sql

BEGIN;

-- 质控相关
TRUNCATE TABLE qc_issues        CASCADE;
TRUNCATE TABLE ai_tasks         CASCADE;

-- 病历版本和病历
TRUNCATE TABLE record_versions  CASCADE;
TRUNCATE TABLE medical_records  CASCADE;

-- 语音和影像
TRUNCATE TABLE voice_records    CASCADE;
TRUNCATE TABLE lab_reports      CASCADE;
TRUNCATE TABLE pacs_images      CASCADE;

-- 问诊输入
TRUNCATE TABLE inquiry_inputs   CASCADE;

-- 接诊（encounter）和患者
TRUNCATE TABLE encounters       CASCADE;
TRUNCATE TABLE patients         CASCADE;

-- 审计日志
TRUNCATE TABLE audit_logs       CASCADE;

COMMIT;

-- 验证（可选）
SELECT 'patients'       AS tbl, COUNT(*) FROM patients
UNION ALL
SELECT 'encounters',    COUNT(*) FROM encounters
UNION ALL
SELECT 'medical_records', COUNT(*) FROM medical_records
UNION ALL
SELECT 'qc_issues',     COUNT(*) FROM qc_issues;
