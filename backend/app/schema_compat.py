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
        ]

        for statement in statements:
            await conn.execute(text(statement))
