"""
补充插入默认质控规则和Prompt模板（仅在表为空时执行）
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def seed():
    async with AsyncSession(engine) as session:
        # 检查质控规则
        r = await session.execute(text("SELECT COUNT(*) FROM qc_rules"))
        if r.scalar() == 0:
            await session.execute(text("""
                INSERT INTO qc_rules (id, name, description, rule_type, field_name, condition, risk_level, is_active, created_at, updated_at) VALUES
                (gen_random_uuid(), '主诉不能为空', '病历主诉字段为必填项，不得留空', 'completeness', 'chief_complaint', '不能为空', 'high', true, NOW(), NOW()),
                (gen_random_uuid(), '现病史不能为空', '现病史是病历核心内容，不得留空', 'completeness', 'history_present_illness', '不能为空', 'high', true, NOW(), NOW()),
                (gen_random_uuid(), '初步诊断不能为空', '须填写初步诊断意见', 'completeness', 'initial_diagnosis', '不能为空', 'high', true, NOW(), NOW()),
                (gen_random_uuid(), '主诉不超过20字', '主诉应简明扼要，通常不超过20字', 'format', 'chief_complaint', '长度不超过20字', 'medium', true, NOW(), NOW()),
                (gen_random_uuid(), '过敏史不能为空', '必须明确记录过敏史或否认过敏史', 'completeness', 'allergy_history', '不能为空', 'medium', true, NOW(), NOW()),
                (gen_random_uuid(), '体格检查不能为空', '体格检查结果为必填项', 'completeness', 'physical_exam', '不能为空', 'medium', true, NOW(), NOW())
            """))
            print("[OK] 插入6条默认质控规则")
        else:
            print(f"[SKIP] 质控规则已有数据，跳过")

        # 检查Prompt模板
        r2 = await session.execute(text("SELECT COUNT(*) FROM prompt_templates"))
        if r2.scalar() == 0:
            await session.execute(text("""
                INSERT INTO prompt_templates (id, name, scene, content, version, is_active, created_at, updated_at) VALUES
                (gen_random_uuid(), '门诊病历生成-标准版', 'generate', '你是一名专业的临床病历书写助手。根据问诊信息生成标准化门诊病历。要求：口语转书面医学语言，时间线清晰，符合医疗文书规范，禁止编造未提及内容。', 'v1', true, NOW(), NOW()),
                (gen_random_uuid(), '病历润色-标准版', 'polish', '你是临床病历规范化专家。对病历进行润色：口语转书面语，消除重复，优化逻辑，保持术语准确。禁止添加未提及内容。', 'v1', true, NOW(), NOW()),
                (gen_random_uuid(), '追问建议-标准版', 'inquiry', '你是临床问诊助手。根据问诊信息给出3-5条追问建议，帮助医生补充关键信息。关注危险信号、病程特征、伴随症状。', 'v1', true, NOW(), NOW()),
                (gen_random_uuid(), 'AI质控-标准版', 'qc', '你是临床病历质控专家。检查病历完整性、规范性和逻辑性，找出缺漏和不规范之处，按高中低危分级输出。', 'v1', true, NOW(), NOW())
            """))
            print("[OK] 插入4条默认Prompt模板")
        else:
            print(f"[SKIP] Prompt模板已有数据，跳过")

        await session.commit()
        print("[OK] 完成")


if __name__ == "__main__":
    asyncio.run(seed())
