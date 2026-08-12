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


async def _inspect() -> tuple[str | None, bool]:
    """读库状态：(alembic_version 当前值或 None, 是否已有业务表)。"""
    from app.database import engine

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
    await engine.dispose()
    return current, has_users is not None


def main() -> None:
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config("alembic.ini")
    known = {rev.revision for rev in ScriptDirectory.from_config(cfg).walk_revisions()}

    current, has_tables = asyncio.run(_inspect())

    if current in known:
        print(f"[alembic-guard] 版本正常（{current}），交给 upgrade")
        return
    if current is None and not has_tables:
        print("[alembic-guard] 全新空库，upgrade 将从基线建表")
        return

    # 老库：表已存在但版本缺失 / 指向已删除的旧链 → 打标记到基线（零 DDL）。
    # purge=True 先清掉 alembic_version 里无法解析的旧值再写入基线。
    print(f"[alembic-guard] 存量库（version={current!r}）→ stamp 到基线 {BASELINE}")
    command.stamp(cfg, BASELINE, purge=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # 守卫失败必须让 entrypoint 停下，不能带病 upgrade
        print(f"[alembic-guard] FATAL: {exc}", file=sys.stderr)
        raise
