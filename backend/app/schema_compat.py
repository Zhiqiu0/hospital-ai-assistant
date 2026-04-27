from sqlalchemy import text

from app.database import Base, engine


async def apply_schema_compatibility() -> None:
    from app.models import audit_log, config, encounter, medical_record, patient, user, voice_record, imaging, lab_report, revoked_token  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        statements = [
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS history_informant TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS current_medications TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS rehabilitation_assessment TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS religion_belief TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS marital_history TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS menstrual_history TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS family_history TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS pain_assessment TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS vte_risk TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS nutrition_assessment TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS psychology_assessment TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS auxiliary_exam TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS admission_diagnosis TEXT",
            # 门诊中医四诊
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS tcm_inspection TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS tcm_auscultation TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS tongue_coating TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS pulse_condition TEXT",
            # 门诊诊断细化
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS western_diagnosis TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS tcm_disease_diagnosis TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS tcm_syndrome_diagnosis TEXT",
            # 治疗意见
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS treatment_method TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS treatment_plan TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS followup_advice TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS precautions TEXT",
            # 急诊附加
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS observation_notes TEXT",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS patient_disposition TEXT",
            # 时间
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS visit_time VARCHAR(30)",
            "ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS onset_time VARCHAR(50)",
            # 影像报告：签发责任人（与分析人 radiologist_id 解耦），用于审计链
            "ALTER TABLE imaging_reports ADD COLUMN IF NOT EXISTS published_by VARCHAR",
            # R1 迁移：影像研究新增 DICOM 标准 UID，用于与 Orthanc/外部 PACS 互通
            "ALTER TABLE imaging_studies ADD COLUMN IF NOT EXISTS study_instance_uid VARCHAR(128) UNIQUE",
            "CREATE INDEX IF NOT EXISTS idx_imaging_studies_study_instance_uid ON imaging_studies(study_instance_uid)",
            # R1 迁移：storage_dir 改为可空（旧数据保留路径，新数据为 NULL）
            "ALTER TABLE imaging_studies ALTER COLUMN storage_dir DROP NOT NULL",
            # ── 患者档案 JSONB 重构（地基级改造）─────────────────────────────────
            # 原：patients.profile_past_history / profile_allergy_history / ... 共 8 个 TEXT 列
            #     + profile_updated_at（整体一个时间戳，粒度过粗）
            # 新：patients.profile JSONB，结构 {<field>: {value, updated_at, updated_by}}
            #     - 字段级 updated_at + updated_by（FHIR verificationStatus 思路）
            #     - 月经史不再放档案（时变信息，每次接诊在 inquiry_inputs.menstrual_history 重填）
            # 旧 8 列在 DB 中保留作为历史归档（model 不再映射），便于回滚
            "ALTER TABLE patients ADD COLUMN IF NOT EXISTS profile JSONB DEFAULT '{}'::jsonb",
        ]

        for statement in statements:
            await conn.execute(text(statement))

        # 一次性数据迁移：把 8 个老 TEXT 列的值搬到新 profile JSONB
        # 仅迁移月经史以外的 7 个字段（地基重构：月经史走问诊不走档案）
        # 仅在 profile 为空 dict 的患者上执行，避免重复迁移
        await conn.execute(text("""
            UPDATE patients
            SET profile = jsonb_strip_nulls(jsonb_build_object(
                'past_history', CASE
                    WHEN profile_past_history IS NOT NULL AND profile_past_history <> ''
                    THEN jsonb_build_object('value', profile_past_history,
                                            'updated_at', COALESCE(profile_updated_at, NOW()),
                                            'updated_by', NULL)
                END,
                'allergy_history', CASE
                    WHEN profile_allergy_history IS NOT NULL AND profile_allergy_history <> ''
                    THEN jsonb_build_object('value', profile_allergy_history,
                                            'updated_at', COALESCE(profile_updated_at, NOW()),
                                            'updated_by', NULL)
                END,
                'family_history', CASE
                    WHEN profile_family_history IS NOT NULL AND profile_family_history <> ''
                    THEN jsonb_build_object('value', profile_family_history,
                                            'updated_at', COALESCE(profile_updated_at, NOW()),
                                            'updated_by', NULL)
                END,
                'personal_history', CASE
                    WHEN profile_personal_history IS NOT NULL AND profile_personal_history <> ''
                    THEN jsonb_build_object('value', profile_personal_history,
                                            'updated_at', COALESCE(profile_updated_at, NOW()),
                                            'updated_by', NULL)
                END,
                'current_medications', CASE
                    WHEN profile_current_medications IS NOT NULL AND profile_current_medications <> ''
                    THEN jsonb_build_object('value', profile_current_medications,
                                            'updated_at', COALESCE(profile_updated_at, NOW()),
                                            'updated_by', NULL)
                END,
                'marital_history', CASE
                    WHEN profile_marital_history IS NOT NULL AND profile_marital_history <> ''
                    THEN jsonb_build_object('value', profile_marital_history,
                                            'updated_at', COALESCE(profile_updated_at, NOW()),
                                            'updated_by', NULL)
                END,
                'religion_belief', CASE
                    WHEN profile_religion_belief IS NOT NULL AND profile_religion_belief <> ''
                    THEN jsonb_build_object('value', profile_religion_belief,
                                            'updated_at', COALESCE(profile_updated_at, NOW()),
                                            'updated_by', NULL)
                END
            ))
            WHERE profile IS NULL OR profile = '{}'::jsonb
        """))
