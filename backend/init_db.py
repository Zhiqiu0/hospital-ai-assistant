"""
数据库初始化脚本
运行一次，创建所有表并插入默认数据
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine, Base
from app.models import user, patient, encounter, medical_record, config, audit_log  # noqa
from app.models.voice_record import VoiceRecord  # noqa  – voice_records 表
# config.py 已包含 ModelConfig（model_configs 表）和 QCRule、PromptTemplate
from app.core.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def init():
    print("正在创建数据库表（已存在的表会跳过）...")
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgcrypto"'))
        await conn.run_sync(Base.metadata.create_all)
    print("[OK] 数据库表创建完成")

    # 插入默认数据
    async with AsyncSession(engine) as session:
        # 检查是否已有数据
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        count = result.scalar()
        if count > 0:
            print("[SKIP] 数据已存在，跳过初始化数据")
            return

        # 创建默认科室
        now = "NOW()"
        await session.execute(text("""
            INSERT INTO departments (id, name, code, is_active, created_at, updated_at) VALUES
            (gen_random_uuid(), '内科', 'NEIKE', true, NOW(), NOW()),
            (gen_random_uuid(), '外科', 'WAIKE', true, NOW(), NOW()),
            (gen_random_uuid(), '急诊科', 'JIZHEN', true, NOW(), NOW()),
            (gen_random_uuid(), '儿科', 'ERKE', true, NOW(), NOW())
        """))

        # 创建默认管理员
        admin_id = "00000000-0000-0000-0000-000000000001"
        pwd_hash = hash_password("admin123456")
        await session.execute(text("""
            INSERT INTO users (id, username, password_hash, real_name, role, is_active, created_at, updated_at)
            VALUES (:id, 'admin', :pwd, '系统管理员', 'super_admin', true, NOW(), NOW())
        """), {"id": admin_id, "pwd": pwd_hash})

        # 创建测试医生账号
        dept_result = await session.execute(
            text("SELECT id FROM departments WHERE code='NEIKE' LIMIT 1")
        )
        dept_id = dept_result.scalar()
        doctor_pwd = hash_password("doctor123")
        await session.execute(text("""
            INSERT INTO users (id, username, password_hash, real_name, role, department_id, employee_no, is_active, created_at, updated_at)
            VALUES (gen_random_uuid(), 'doctor01', :pwd, '张医生', 'doctor', :dept_id, 'EMP001', true, NOW(), NOW())
        """), {"pwd": doctor_pwd, "dept_id": dept_id})

        # 插入默认质控规则
        await session.execute(text("""
            INSERT INTO qc_rules (id, name, description, rule_type, field_name, condition, risk_level, is_active, created_at, updated_at) VALUES
            (gen_random_uuid(), '主诉不能为空', '病历主诉字段为必填项，不得留空', 'completeness', 'chief_complaint', '不能为空', 'high', true, NOW(), NOW()),
            (gen_random_uuid(), '现病史不能为空', '现病史是病历核心内容，不得留空', 'completeness', 'history_present_illness', '不能为空', 'high', true, NOW(), NOW()),
            (gen_random_uuid(), '初步诊断不能为空', '须填写初步诊断意见', 'completeness', 'initial_diagnosis', '不能为空', 'high', true, NOW(), NOW()),
            (gen_random_uuid(), '主诉不超过20字', '主诉应简明扼要，通常不超过20字', 'format', 'chief_complaint', '长度不超过20字', 'medium', true, NOW(), NOW()),
            (gen_random_uuid(), '过敏史不能为空', '必须明确记录过敏史或否认过敏史', 'completeness', 'allergy_history', '不能为空', 'medium', true, NOW(), NOW()),
            (gen_random_uuid(), '体格检查不能为空', '体格检查结果为必填项', 'completeness', 'physical_exam', '不能为空', 'medium', true, NOW(), NOW())
        """))

        # 插入默认 Prompt 模板
        await session.execute(text("""
            INSERT INTO prompt_templates (id, name, scene, content, version, is_active, created_at, updated_at) VALUES
            (gen_random_uuid(), '门诊病历生成-标准版', 'generate',
            '你是一名专业的临床病历书写助手。根据以下问诊信息，生成标准化的门诊病历草稿。

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
个人史：{personal_history}
体格检查：{physical_exam}
初步印象：{initial_impression}

请生成规范的病历文本，包含【主诉】【现病史】【既往史】【个人史及过敏史】【体格检查】【初步诊断】各节。
要求：口语转书面医学语言，时间线清晰，符合医疗文书规范，禁止编造未提及的症状。',
            'v1', true, NOW(), NOW()),
            (gen_random_uuid(), '病历润色-标准版', 'polish',
            '你是临床病历规范化专家。请对以下病历内容进行润色：
1. 将口语转换为书面医学语言
2. 消除重复和冗余内容
3. 优化时间顺序，使叙述逻辑清晰
4. 保持医学术语的准确性
5. 禁止添加原文未提及的内容

原始病历：
{content}

请直接输出润色后的病历文本，格式与原文保持一致。',
            'v1', true, NOW(), NOW())
        """))

        await session.commit()
        print("[OK] 默认数据插入完成")
        print("")
        print("===================================")
        print("  默认账号：")
        print("  管理员  - admin / admin123456")
        print("  测试医生 - doctor01 / doctor123")
        print("===================================")


if __name__ == "__main__":
    asyncio.run(init())
