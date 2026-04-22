"""
增量迁移脚本 - 安全执行，已存在的表/列会跳过
用法：python migrate.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine, Base
from sqlalchemy import text


# 导入所有模型，确保 Base.metadata 包含全部表定义
from app.models import user, patient, encounter, medical_record, config, audit_log  # noqa
from app.models.voice_record import VoiceRecord  # noqa
from app.models.inpatient import VitalSign, ProblemItem  # noqa
# config.py 里已有 ModelConfig，上面 config 导入已覆盖


async def migrate():
    print("=== MediScribe 增量迁移 ===\n")

    async with engine.begin() as conn:

        # 1. 新建缺失的表（create_all 对已存在的表不做任何修改）
        print("[1] 创建缺失的表（已存在的跳过）...")
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        await conn.run_sync(Base.metadata.create_all)
        print("    OK\n")

        # 2. InquiryInput 新增字段（住院部扩展字段，旧库可能没有）
        print("[2] InquiryInput 新增住院扩展字段...")
        new_inquiry_columns = [
            ("history_informant",        "TEXT"),
            ("current_medications",      "TEXT"),
            ("rehabilitation_assessment","TEXT"),
            ("religion_belief",          "TEXT"),
        ]
        for col, col_type in new_inquiry_columns:
            try:
                await conn.execute(text(
                    f"ALTER TABLE inquiry_inputs ADD COLUMN IF NOT EXISTS {col} {col_type}"
                ))
                print(f"    inquiry_inputs.{col} - OK")
            except Exception as e:
                print(f"    inquiry_inputs.{col} - SKIP ({e})")
        print()

        # 3. Encounter 新增字段（如有需要）
        print("[3] Encounter 检查字段...")
        encounter_columns = [
            ("chief_complaint_brief", "VARCHAR(200)"),
            ("bed_no",                "VARCHAR(20)"),
            ("admission_route",       "VARCHAR(20)"),
            ("admission_condition",   "VARCHAR(10)"),
            ("completed_at",          "TIMESTAMP"),
        ]
        for col, col_type in encounter_columns:
            try:
                await conn.execute(text(
                    f"ALTER TABLE encounters ADD COLUMN IF NOT EXISTS {col} {col_type}"
                ))
                print(f"    encounters.{col} - OK")
            except Exception as e:
                print(f"    encounters.{col} - SKIP ({e})")
        print()

        # 4. VoiceRecord audio_file_path 长度可能不够（旧版 String(300)）
        print("[4] VoiceRecord 字段检查...")
        try:
            await conn.execute(text(
                "ALTER TABLE voice_records ALTER COLUMN audio_file_path TYPE VARCHAR(500)"
            ))
            print("    voice_records.audio_file_path - OK")
        except Exception as e:
            print(f"    voice_records.audio_file_path - SKIP ({e})")
        print()

        # 5. qc_issues.medical_record_id 改为可为空（快速质控无需关联病历记录）
        print("[5] qc_issues.medical_record_id 改为可为空...")
        try:
            await conn.execute(text(
                "ALTER TABLE qc_issues ALTER COLUMN medical_record_id DROP NOT NULL"
            ))
            print("    qc_issues.medical_record_id - OK")
        except Exception as e:
            print(f"    qc_issues.medical_record_id - SKIP ({e})")
        print()

        # 6a. Patient 档案字段：过敏/既往/家族/个人/用药等迁到患者级别（FHIR 对齐）
        print("[6a] patients 新增 profile_* 档案字段...")
        patient_profile_columns = [
            ("profile_past_history",        "TEXT"),
            ("profile_allergy_history",     "TEXT"),
            ("profile_family_history",      "TEXT"),
            ("profile_personal_history",    "TEXT"),
            ("profile_current_medications", "TEXT"),
            ("profile_marital_history",     "TEXT"),
            ("profile_menstrual_history",   "TEXT"),
            ("profile_religion_belief",     "TEXT"),
            ("profile_updated_at",          "TIMESTAMP"),
        ]
        for col, col_type in patient_profile_columns:
            try:
                await conn.execute(text(
                    f"ALTER TABLE patients ADD COLUMN IF NOT EXISTS {col} {col_type}"
                ))
                print(f"    patients.{col} - OK")
            except Exception as e:
                print(f"    patients.{col} - SKIP ({e})")
        print()

        # 6b. 回填：把每个患者最后一次接诊里非空的档案字段拷到 patients.profile_*
        #     只回填当前 profile_* 为空的患者，已手动填过的不覆盖
        print("[6b] 回填 patients.profile_* （取每个患者最后一次非空的接诊值）...")
        profile_field_map = {
            "profile_past_history":        "past_history",
            "profile_allergy_history":     "allergy_history",
            "profile_family_history":      "family_history",
            "profile_personal_history":    "personal_history",
            "profile_current_medications": "current_medications",
            "profile_marital_history":     "marital_history",
            "profile_menstrual_history":   "menstrual_history",
            "profile_religion_belief":     "religion_belief",
        }
        for profile_col, inquiry_col in profile_field_map.items():
            try:
                # 子查询：对每个 patient 取该字段最新非空值
                result = await conn.execute(text(f"""
                    UPDATE patients p
                    SET {profile_col} = sub.val,
                        profile_updated_at = COALESCE(p.profile_updated_at, sub.updated_at)
                    FROM (
                        SELECT DISTINCT ON (e.patient_id)
                               e.patient_id,
                               i.{inquiry_col} AS val,
                               i.updated_at
                        FROM inquiry_inputs i
                        JOIN encounters e ON e.id = i.encounter_id
                        WHERE i.{inquiry_col} IS NOT NULL AND i.{inquiry_col} <> ''
                        ORDER BY e.patient_id, i.updated_at DESC
                    ) sub
                    WHERE p.id = sub.patient_id
                      AND (p.{profile_col} IS NULL OR p.{profile_col} = '')
                """))
                print(f"    {profile_col} ← inquiry_inputs.{inquiry_col}  更新 {result.rowcount} 条")
            except Exception as e:
                print(f"    {profile_col} - SKIP ({e})")
        print()

        # 7. qc_rules 重构：新增 rule_code / scope / keywords 等字段
        print("[6] qc_rules 新增扩展字段...")
        qc_rules_columns = [
            ("rule_code",            "VARCHAR(20)"),
            ("scope",                "VARCHAR(20)"),
            ("keywords",             "TEXT"),
            ("indication_keywords",  "TEXT"),
            ("issue_description",    "TEXT"),
            ("suggestion",           "TEXT"),
            ("score_impact",         "VARCHAR(20)"),
            # gender_scope：按患者性别过滤规则（all/female/male）
            ("gender_scope",         "VARCHAR(10) DEFAULT 'all'"),
        ]
        for col, col_type in qc_rules_columns:
            try:
                await conn.execute(text(
                    f"ALTER TABLE qc_rules ADD COLUMN IF NOT EXISTS {col} {col_type}"
                ))
                print(f"    qc_rules.{col} - OK")
            except Exception as e:
                print(f"    qc_rules.{col} - SKIP ({e})")
        print()

    print("=== 迁移完成 ===")


if __name__ == "__main__":
    asyncio.run(migrate())
