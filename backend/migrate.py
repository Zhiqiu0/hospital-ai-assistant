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

    print("=== 迁移完成 ===")


if __name__ == "__main__":
    asyncio.run(migrate())
