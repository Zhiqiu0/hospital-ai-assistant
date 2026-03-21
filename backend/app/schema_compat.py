from sqlalchemy import text

from app.database import Base, engine


async def apply_schema_compatibility() -> None:
    from app.models import audit_log, config, encounter, medical_record, patient, user, voice_record, imaging, lab_report  # noqa: F401

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
        ]

        for statement in statements:
            await conn.execute(text(statement))
