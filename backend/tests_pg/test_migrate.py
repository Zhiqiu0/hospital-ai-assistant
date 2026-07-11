"""
migrate.py 真 PG 测试（盲区 #2：直改生产 schema 的脚本零测试）

migrate.py 用的是 PG 专属 DDL（JSONB、ALTER TYPE ... USING、information_schema
探测），SQLite 根本测不了。覆盖：
  - 幂等：连跑两次 migrate() 不报错（AUTOCOMMIT 下每条 ALTER 独立，重复无害）
  - ALTER 的列/类型符合预期：voice_records.audio_file_path 被拉宽到 VARCHAR(500)
  - 历史事故点：老 DB 里 qc_rules.keywords 曾是 TEXT，migrate 的 ALTER TYPE
    ... USING ...::jsonb 应把它转成 JSONB，转完是真 JSON 数组（不是字符串）
"""

import uuid

import migrate  # noqa: E402  # conftest 已把 app.database.engine 换成一次性测试库
from sqlalchemy import text


async def _column_info(engine, table: str, column: str) -> dict:
    """取某列的 data_type 和 character_maximum_length。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT data_type, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"
            ),
            {"t": table, "c": column},
        )
        row = result.first()
        return {"data_type": row[0], "max_length": row[1]} if row else {}


async def test_migrate_idempotent_and_audio_path_widened(empty_pg):
    """空库上连跑两次 migrate()：不报错（幂等）+ audio_file_path 被拉到 VARCHAR(500)。"""
    engine = empty_pg

    # 第一次：create_all 建表 + 全部 ALTER
    await migrate.migrate()
    # 第二次：全部应幂等，不抛异常
    await migrate.migrate()

    info = await _column_info(engine, "voice_records", "audio_file_path")
    assert info.get("data_type") == "character varying", f"实际类型 {info}"
    assert info.get("max_length") == 500, f"audio_file_path 长度应为 500，实际 {info}"


async def test_migrate_converts_legacy_text_keywords_to_jsonb(pg_with_tables):
    """还原「老库 keywords 是 TEXT」的场景，验证 migrate 把它正确转成 JSONB 数组。

    这是历史事故的根因路径：早期 keywords 是 TEXT，反序列化时 Pydantic 拿到 str
    触发 500。migrate 的 ALTER TYPE ... USING CASE ... ::jsonb 负责把老 TEXT 转过去。
    pg_with_tables 已 create_all（keywords 为 json），这里先把它降级成 TEXT 模拟老库。
    """
    engine = pg_with_tables

    # 1) 把 keywords 降级成 TEXT，模拟历史老库结构
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE qc_rules ALTER COLUMN keywords TYPE TEXT USING keywords::text"
        ))
    assert (await _column_info(engine, "qc_rules", "keywords"))["data_type"] == "text"

    # 2) 塞一条 keywords 为「JSON 数组字符串」的老数据（补齐 NOT NULL 列）
    rid = str(uuid.uuid4())
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO qc_rules "
                "(id, rule_code, name, scope, gender_scope, is_active, keywords, created_at, updated_at) "
                "VALUES (:id, 'LEGACY_KW', '老库关键词', 'all', 'all', true, :kw, NOW(), NOW())"
            ),
            {"id": rid, "kw": '["主诉", "C/O"]'},
        )

    # 3) 跑 migrate：keywords 当前是 text ≠ jsonb → 触发 ALTER TYPE ... USING ...::jsonb
    await migrate.migrate()

    # 4) 列类型应变成 jsonb
    assert (await _column_info(engine, "qc_rules", "keywords"))["data_type"] == "jsonb", \
        "migrate 应把老 TEXT keywords 转成 JSONB"

    # 5) 值应是真 JSON 数组（jsonb_typeof=array），而不是被当成一整个字符串
    async with engine.connect() as conn:
        typ = (await conn.execute(
            text("SELECT jsonb_typeof(keywords) FROM qc_rules WHERE id=:id"), {"id": rid}
        )).scalar()
        first = (await conn.execute(
            text("SELECT keywords->>0 FROM qc_rules WHERE id=:id"), {"id": rid}
        )).scalar()
    assert typ == "array", f"转换后应为 JSON 数组，实际 jsonb_typeof={typ}"
    assert first == "主诉", f"数组首元素应为 '主诉'，实际 {first}"
