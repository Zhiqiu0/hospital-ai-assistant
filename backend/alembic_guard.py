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
from pathlib import Path

from sqlalchemy import text

# 基线 revision ID，与 alembic/versions/b20260812squash_*.py 保持一致
BASELINE = "b20260812squash"

# 基线 DDL 快照，列级校验的比对基准（见 _baseline_columns 说明）
BASELINE_SQL = Path(__file__).parent / "alembic" / "versions" / "b20260812squash_schema.sql"

# 基线 DDL 里表示"这一行不是列定义"的关键字（约束/键行）
_NON_COLUMN_TOKENS = {"PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK", "EXCLUDE"}

# 基线里有、但已被基线之后的迁移**删除**的表（2026-08-14 新增）
#
# 守卫的语义是「这个库的 schema 等于基线」，据此拒绝给缺列的库 stamp。
# 但一张表被后续迁移删掉之后，情况反过来了：
#   · 老库（停在基线附近）**有**这张表 → 与基线一致，本该放行
#   · 而它的列在模型里已经没有了
# 若不豁免，守卫会拿基线里的旧表去要求库必须有它，而删表迁移执行过的库
# 反倒被判为"缺列"——一个刚跑完 upgrade 的健康库会被拒绝 stamp。
# 这里显式登记这类表：它们在不在都不影响"是否可以 stamp 到基线"的判断。
#
# 加新条目时必须写清是哪条迁移删的，避免变成一个无人敢动的黑名单。
_DROPPED_SINCE_BASELINE = {
    # l20260814dropnotes：住院文书统一到 medical_records 后删除（生产 0 行）
    "progress_notes",
    # n20260818dropaicfg：撤掉后台「模型配置」「Prompt 管理」两页后删除，
    # 模型参数与提示词归代码维护（生产仅默认/不生效的种子行）
    "model_configs",
    "prompt_templates",
}


def _baseline_columns() -> set[tuple[str, str]]:
    """从冻结的基线 DDL 解析出 {(表名, 列名)}。

    为什么不用 Base.metadata（2026-08-13 修正）：
      stamp 的语义是"这个库的 schema 等于**基线**"，之后由 upgrade 把基线之后的
      迁移逐条补上。原先拿当前模型元数据去比对，等于要求存量库预先具备后续迁移
      才会加的列——只要有人加一条加列迁移（本次 doctor_codes / must_change_password
      就是），真正的存量库就必然"缺列"而被拒绝 stamp，守卫从此永远误报。
      改为对齐冻结的基线快照后，判断口径与 stamp 的语义一致。
    """
    text_sql = BASELINE_SQL.read_text(encoding="utf-8")
    columns: set[tuple[str, str]] = set()
    table: str | None = None
    for raw in text_sql.splitlines():
        line = raw.strip().rstrip(",").strip()
        if line.upper().startswith("CREATE TABLE"):
            table = line.split()[2].strip("(").strip()
            continue
        if table is None or not line:
            continue
        if line.startswith(")") or line == ");":
            table = None
            continue
        first = line.split()[0].upper()
        if first in _NON_COLUMN_TOKENS:
            continue
        columns.add((table, line.split()[0]))
    return columns


async def _inspect() -> tuple[str | None, bool, list[str]]:
    """读库状态：(alembic_version 当前值或 None, 是否已有业务表, 缺失列清单)。

    缺失列清单（2026-08-12 复检修复）：拿基线 DDL 的表/列清单查 information_schema。
    stamp 只该发生在"schema 与基线一致的存量库"上——若库是从旧备份恢复的
    （停在旧链中段、缺基线里就该有的列），带病 stamp 会让缺口永远补不上且无人知晓。
    """
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

        missing: list[str] = []
        if has_users is not None:
            rows = await conn.execute(text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            ))
            existing = {(t, c) for t, c in rows}
            missing = sorted(
                f"{tbl}.{col}"
                for tbl, col in _baseline_columns()
                # 已被后续迁移删掉的表不参与比对（见 _DROPPED_SINCE_BASELINE）
                if tbl not in _DROPPED_SINCE_BASELINE and (tbl, col) not in existing
            )
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
