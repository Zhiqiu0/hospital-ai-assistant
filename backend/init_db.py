"""
默认种子数据脚本（init_db.py）

2026-08-12 迁移收口后职责收窄：**只播种子，不再建表**——表结构（含索引/
约束/触发器）统一由 alembic 负责（基线 b20260812squash 起），本脚本在
entrypoint 里排在 `alembic upgrade head` 之后执行，表必然已就绪。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine
from app.core.security import hash_password
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def init():
    # 插入默认数据（表结构由 alembic 建好，这里直接播种）
    async with AsyncSession(engine) as session:
        # 检查是否已有数据
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        count = result.scalar()
        if count > 0:
            print("[SKIP] 数据已存在，跳过初始化数据")
            return

        # 创建默认科室
        await session.execute(text("""
            INSERT INTO departments (id, name, code, is_active, created_at, updated_at) VALUES
            (gen_random_uuid(), '内科', 'NEIKE', true, NOW(), NOW()),
            (gen_random_uuid(), '外科', 'WAIKE', true, NOW(), NOW()),
            (gen_random_uuid(), '急诊科', 'JIZHEN', true, NOW(), NOW()),
            (gen_random_uuid(), '儿科', 'ERKE', true, NOW(), NOW())
        """))

        # 创建默认管理员
        # 密码从环境变量读，缺省沿用 admin123456（本地/开发方便）。
        # 生产部署时在 .env 设 SEED_ADMIN_PASSWORD 为强密码即可，不必改代码。
        # 注意：init_db 仅在 users 表为空时执行（见上方 count 判断），
        # 改这里不影响任何已建账号（含生产在用的 admin）。
        admin_id = "00000000-0000-0000-0000-000000000001"
        admin_pwd_plain = os.getenv("SEED_ADMIN_PASSWORD", "admin123456")
        pwd_hash = hash_password(admin_pwd_plain)
        await session.execute(text("""
            INSERT INTO users (id, username, password_hash, real_name, role, is_active, created_at, updated_at)
            VALUES (:id, 'admin', :pwd, '系统管理员', 'super_admin', true, NOW(), NOW())
        """), {"id": admin_id, "pwd": pwd_hash})

        # 创建测试医生账号
        dept_result = await session.execute(
            text("SELECT id FROM departments WHERE code='NEIKE' LIMIT 1")
        )
        dept_id = dept_result.scalar()
        doctor_pwd_plain = os.getenv("SEED_DOCTOR_PASSWORD", "doctor123")
        doctor_pwd = hash_password(doctor_pwd_plain)
        await session.execute(text("""
            INSERT INTO users (id, username, password_hash, real_name, role, department_id, employee_no, is_active, created_at, updated_at)
            VALUES (gen_random_uuid(), 'doctor01', :pwd, '张医生', 'doctor', :dept_id, 'EMP001', true, NOW(), NOW())
        """), {"pwd": doctor_pwd, "dept_id": dept_id})

        # 注：原「默认质控规则」种子已移除（2026-07 修）。
        # 原 INSERT 引用的 qc_rules.condition 列在 QCRule schema 重构（迁移
        # b1c2d3e4f5a6_qc_rules_new_schema）后已不存在、且漏了 NOT NULL 的 rule_code，
        # 在全新库上必然 INSERT 失败——因为所有种子在同一事务里，一挂会把
        # 科室/admin/doctor01/规则/模板整批回滚，导致全新部署"一条种子都进不去"。
        # 而这些完整性检查现在由质控 Rubric 引擎（ZJ_OUTPATIENT_EMERGENCY_V2023 等）
        # 统一负责，qc_rules 表改为承载 admin 后台管理的关键词/医保规则（按需在 UI 添加），
        # 不再需要硬编码默认规则。故此段删除，全新库种子恢复正常。

        # 注：原「默认 Prompt 模板」种子已移除（2026-08-18）——提示词归代码维护，
        # prompt_templates 表已随 alembic 迁移删除。

        await session.commit()
        print("[OK] 默认数据插入完成")
        print("")
        print("===================================")
        print("  默认账号：")
        print(f"  管理员  - admin / {admin_pwd_plain}")
        print(f"  测试医生 - doctor01 / {doctor_pwd_plain}")
        print("  (密码可用 SEED_ADMIN_PASSWORD / SEED_DOCTOR_PASSWORD 覆盖)")
        print("===================================")


if __name__ == "__main__":
    asyncio.run(init())
