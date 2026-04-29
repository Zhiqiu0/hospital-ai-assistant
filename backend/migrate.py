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
from app.models.inpatient import VitalSign, ProblemItem, ProgressNote  # noqa
from app.models.ai_feedback import AISuggestionFeedback  # noqa
# config.py 里已有 ModelConfig，上面 config 导入已覆盖


async def migrate():
    """增量迁移主入口。

    事务粒度（治本于 2026-04-30）：
      - 第 [1] 步 create_all 必须事务保护（建表是原子操作） → 走 engine.begin()
      - 第 [2]+ 步全部 ALTER / UPDATE 改用 AUTOCOMMIT 隔离级别：
          每条 SQL 独立事务，单条失败不污染后续——之前是单一 begin()
          包裹整个函数，任何一条失败 → PG 整个事务 abort →
          后续所有 SQL 抛 InFailedSQLTransactionError 全部 SKIP（误报噪音）
    """
    print("=== MediScribe 增量迁移 ===\n")

    # 第 [1] 步 create_all 需要事务原子性（建表中途失败要回滚）
    async with engine.begin() as conn:
        print("[1] 创建缺失的表（已存在的跳过）...")
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        await conn.run_sync(Base.metadata.create_all)
        print("    OK\n")

    # 第 [2]+ 步用 AUTOCOMMIT：每条 SQL 单独事务，失败相互独立
    async with engine.connect() as raw_conn:
        conn = await raw_conn.execution_options(isolation_level="AUTOCOMMIT")

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

        # 2b. inquiry_inputs 新增生命体征结构化字段（从 physical_exam 文本分离）
        print("[2b] inquiry_inputs 新增生命体征字段...")
        vital_signs_columns = [
            ("temperature",  "VARCHAR(10)"),
            ("pulse",        "VARCHAR(10)"),
            ("respiration",  "VARCHAR(10)"),
            ("bp_systolic",  "VARCHAR(10)"),
            ("bp_diastolic", "VARCHAR(10)"),
            ("spo2",         "VARCHAR(10)"),
            ("height",       "VARCHAR(10)"),
            ("weight",       "VARCHAR(10)"),
        ]
        for col, col_type in vital_signs_columns:
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
            # ⚠️ keywords / indication_keywords 必须用 JSONB——ORM model 声明
            # 是 JSON 列，QCRuleResponse Pydantic schema 要求 List[str]。早期
            # 这里用 TEXT，导致 GET /admin/qc-rules 反序列化时拿到字符串
            # 触发 ValidationError 500。新装幂等：列已存在则跳过 ADD，再走
            # ALTER ... TYPE JSONB USING ::jsonb 把已有 TEXT 转过去。
            ("keywords",             "JSONB"),
            ("indication_keywords",  "JSONB"),
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
        # 兜底：早期版本里 keywords/indication_keywords 是 TEXT，老数据库里
        # 列类型仍是 TEXT。改不动 ADD COLUMN（已存在），需要显式 ALTER TYPE。
        # USING ::jsonb 把已有字符串内容当 JSON 解析；空串 / 非法 JSON 会失败，
        # 但 seed_config 写入的都是合法 JSON 数组，OK。
        for col in ("keywords", "indication_keywords"):
            try:
                await conn.execute(text(
                    f"ALTER TABLE qc_rules ALTER COLUMN {col} TYPE JSONB "
                    f"USING CASE WHEN {col} IS NULL OR {col} = '' "
                    f"THEN NULL ELSE {col}::jsonb END"
                ))
                print(f"    qc_rules.{col} TYPE → JSONB - OK")
            except Exception as e:
                # 已经是 JSONB 的话 ALTER 会成功（无变化），其他情况打日志不阻断
                print(f"    qc_rules.{col} TYPE - SKIP ({str(e)[:80]})")
        print()

        # 7. ai_suggestion_feedback 新增地基字段（为未来档次 2/3 优化做准备）
        # prompt_version: 按 prompt 模板版本区分反馈（跨版本反馈不能混用）
        # prompt_scene:   记录生成 prompt 的场景（inquiry_suggestion / generate / qc 等）
        # model_name:     记录生成该建议的模型（模型换了，旧反馈价值打折）
        print("[7] ai_suggestion_feedback 新增 prompt_version / prompt_scene / model_name 字段...")
        feedback_columns = [
            ("prompt_version", "VARCHAR(20)"),
            ("prompt_scene",   "VARCHAR(50)"),
            ("model_name",     "VARCHAR(100)"),
        ]
        for col, col_type in feedback_columns:
            try:
                await conn.execute(text(
                    f"ALTER TABLE ai_suggestion_feedback ADD COLUMN IF NOT EXISTS {col} {col_type}"
                ))
                print(f"    ai_suggestion_feedback.{col} - OK")
            except Exception as e:
                print(f"    ai_suggestion_feedback.{col} - SKIP ({e})")
        # 索引：按 prompt_version 查历史反馈（未来档次 2 按版本分层最常用）
        try:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_ai_feedback_prompt_version "
                "ON ai_suggestion_feedback (prompt_version)"
            ))
            print("    index ix_ai_feedback_prompt_version - OK")
        except Exception as e:
            print(f"    index ix_ai_feedback_prompt_version - SKIP ({e})")
        print()

        # 8. patients 拼音索引列（兜底，正式版由 alembic d3e4f5a6b7c8 迁移）
        # 之前 .dockerignore 误把 alembic/versions/ 排除导致镜像里没迁移文件，
        # alembic upgrade head 跑空 → 列不存在 → /patients /encounters/my 500。
        # migrate.py 兜底 ALTER + 回填，确保即使 alembic 不可用业务也能跑。
        print("[8] patients 拼音索引列 + 回填存量...")
        for col, col_type in [
            ("name_pinyin",          "VARCHAR(512)"),
            ("name_pinyin_initials", "VARCHAR(128)"),
        ]:
            try:
                await conn.execute(text(
                    f"ALTER TABLE patients ADD COLUMN IF NOT EXISTS {col} {col_type}"
                ))
                print(f"    patients.{col} - OK")
            except Exception as e:
                print(f"    patients.{col} - SKIP ({e})")
        # 回填：仅对 name_pinyin 仍为 NULL 的患者计算（幂等，重复跑不重写已有值）
        try:
            from app.utils.pinyin import compute_pinyin
            result = await conn.execute(text(
                "SELECT id, name FROM patients WHERE name_pinyin IS NULL"
            ))
            rows = result.fetchall()
            n = 0
            for row in rows:
                full, init = compute_pinyin(row.name or "")
                await conn.execute(text(
                    "UPDATE patients SET name_pinyin = :f, name_pinyin_initials = :i "
                    "WHERE id = :id"
                ), {"f": full, "i": init, "id": row.id})
                n += 1
            print(f"    patients 拼音回填 - OK（{n} 条）")
        except Exception as e:
            print(f"    patients 拼音回填 - SKIP ({str(e)[:80]})")
        print()

    print("=== 迁移完成 ===")


if __name__ == "__main__":
    asyncio.run(migrate())
