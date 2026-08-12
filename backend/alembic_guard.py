"""alembic 前置守卫（backend/alembic_guard.py）

2026-08-12 迁移四通道收口：alembic 成为唯一迁移通道后，存量库的
alembic_version 可能是空的（历史上只跑 migrate.py）或指向已被压缩重置
删掉的旧 revision——直接 `alembic upgrade head` 会报"找不到 revision"。

本脚本在 upgrade 之前跑，只做一件事：判断库的状态并在必要时打标记（stamp），
**绝不执行任何 DDL**：
  - alembic_version 指向新链已知 revision → 正常，什么都不做
  - 全新空库（连 users 表都没有）      → 什么都不做，upgrade 会从基线建表
  - 老库（表在，但版本缺失/指向旧链）   → stamp 到基线（纯写标记，零 DDL）

用法：python alembic_guard.py && alembic upgrade head
"""
import asyncio
import sys

from sqlalchemy import text

# 基线 revision ID，与 alembic/versions/b20260812squash_*.py 保持一致
BASELINE = "b20260812squash"


async def _inspect() -> tuple[str | None, bool, list[str]]:
    """读库状态：(alembic_version 当前值或 None, 是否已有业务表, 缺失列清单)。

    缺失列清单（2026-08-12 复检修复）：对模型元数据逐表逐列查 information_schema。
    stamp 只该发生在"schema 与基线一致的存量库"上——若库是从旧备份恢复的
    （停在旧链中段、缺后来加的列），带病 stamp 会让缺口永远补不上且无人知晓。
    """
    from app.database import Base, engine
    # 与 alembic/env.py 同一清单：导全模型让 Base.metadata 完整
    import app.models.user            # noqa: F401
    import app.models.patient         # noqa: F401
    import app.models.encounter      # noqa: F401
    import app.models.medical_record  # noqa: F401
    import app.models.audit_log       # noqa: F401
    import app.models.config          # noqa: F401
    import app.models.voice_record    # noqa: F401
    import app.models.imaging         # noqa: F401
    import app.models.lab_report      # noqa: F401
    import app.models.revoked_token   # noqa: F401
    import app.models.inpatient       # noqa: F401
    import app.models.ai_feedback     # noqa: F401

    async with engine.connect() as conn:
        has_users = (
            await conn.execute(text("SELECT to_regclass('public.users')"))
        ).scalar()
        has_version_table = (
            await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
        ).scalar()
        current = None
        if has_version_table:
            current = (
                await conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
            ).scalar()

        missing: list[str] = []
        if has_users is not None:
            rows = await conn.execute(text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            ))
            existing = {(t, c) for t, c in rows}
            missing = [
                f"{table.name}.{col.name}"
                for table in Base.metadata.sorted_tables
                for col in table.columns
                if (table.name, col.name) not in existing
            ]
    await engine.dispose()
    return current, has_users is not None, missing


def main() -> None:
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config("alembic.ini")
    known = {rev.revision for rev in ScriptDirectory.from_config(cfg).walk_revisions()}

    current, has_tables, missing = asyncio.run(_inspect())

    if current in known:
        print(f"[alembic-guard] 版本正常（{current}），交给 upgrade")
        return
    if current is None and not has_tables:
        print("[alembic-guard] 全新空库，upgrade 将从基线建表")
        return

    # 带病 stamp 拦截（2026-08-12 复检修复）：库若缺模型声明的列（典型场景=
    # 从压缩重置前的旧备份恢复，停在旧链中段），stamp 会把缺口永久掩盖——
    # upgrade 无事可做、所有工具声称在 head、运行期随机 500 且排障无线索。
    # 这里显式失败，把静默事故变成明确的操作指引。
    if missing:
        raise RuntimeError(
            f"库 schema 与模型不一致，拒绝 stamp（缺 {len(missing)} 列）：{missing[:10]}...\n"
            "典型原因：恢复了压缩重置(2026-08-12)之前的旧备份。处理：改用重置后的"
            "备份恢复；或人工补齐缺失列后重跑。"
        )

    # 老库：表已存在但版本缺失 / 指向已删除的旧链，且列级校验通过 →
    # 打标记到基线（零 DDL）。purge=True 先清掉无法解析的旧值再写入基线。
    print(f"[alembic-guard] 存量库（version={current!r}，列级校验通过）→ stamp 到基线 {BASELINE}")
    command.stamp(cfg, BASELINE, purge=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 守卫失败必须让 entrypoint 停下，不能带病 upgrade
        print(f"[alembic-guard] FATAL: {exc}", file=sys.stderr)
        raise
