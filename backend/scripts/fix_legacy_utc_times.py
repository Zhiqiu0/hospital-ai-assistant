# -*- coding: utf-8 -*-
"""存量 UTC 时间一次性校正为北京时间（2026-08-11 时区统一配套，生产只跑一次）。

背景：
  生产容器此前默认 UTC，datetime.now() 落库的全部 naive 时间实际是 UTC，
  前端按本地(北京)解析显示差 8 小时。compose 加 TZ=Asia/Shanghai 后新数据
  即为北京时间；本脚本把「切换时刻之前写入的存量行」整体 +8 小时对齐。

安全设计：
  - 只在部署了 TZ 的新容器里、切换后立刻手动执行一次（docker exec）；
  - cutoff 保护：仅移动「值 <= 当前 UTC 时刻」的行——存量 UTC 值必然满足，
    切换后新写入的北京值必然大于 cutoff（快 8 小时），绝不会被二次平移；
  - revoked_tokens.expires_at 是"未来时间"不满足 cutoff，单独无条件平移
    （该表当前行数极少，且语义随写入口径一起切换）；
  - medical_records.patient_snapshot(JSONB) 里的 visit_time ISO 字符串
    随行补正（病案首页快照，合规展示用）；
  - 先跑 --dry-run 看清将影响的行数，确认后去掉参数真跑。

用法（生产容器内）：
  docker exec app-backend-1 python scripts/fix_legacy_utc_times.py --dry-run
  docker exec app-backend-1 python scripts/fix_legacy_utc_times.py
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 引 app 包

from sqlalchemy import text  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402

SHIFT_HOURS = 8


async def main(dry_run: bool) -> None:
    # cutoff 取脚本运行时的 UTC 时刻：存量 UTC 值 <= 它；新北京值 > 它（快 8h）
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None)
    print(f"[cutoff] {cutoff.isoformat()} (UTC)  dry_run={dry_run}")

    async with AsyncSessionLocal() as db:
        # 1. 枚举所有 timestamp 列（跳过 alembic 版本表；revoked_tokens 单独处理）
        cols = (await db.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type LIKE 'timestamp%' "
            "AND table_name NOT IN ('alembic_version', 'revoked_tokens') "
            "ORDER BY table_name, column_name"
        ))).all()

        total = 0
        for table, col in cols:
            sql = (
                f'UPDATE "{table}" SET "{col}" = "{col}" + INTERVAL \'{SHIFT_HOURS} hours\' '
                f'WHERE "{col}" IS NOT NULL AND "{col}" <= :cutoff'
            )
            if dry_run:
                n = (await db.execute(text(
                    f'SELECT count(*) FROM "{table}" '
                    f'WHERE "{col}" IS NOT NULL AND "{col}" <= :cutoff'
                ), {"cutoff": cutoff})).scalar()
            else:
                n = (await db.execute(text(sql), {"cutoff": cutoff})).rowcount
            if n:
                print(f"  {table}.{col}: {n} 行")
                total += n

        # 2. revoked_tokens：expires_at 是未来时间，无条件平移；revoked_at 走 cutoff
        for col, cond in (("expires_at", ""), ("revoked_at", "AND revoked_at <= :cutoff")):
            sql = (
                f"UPDATE revoked_tokens SET {col} = {col} + INTERVAL '{SHIFT_HOURS} hours' "
                f"WHERE {col} IS NOT NULL {cond}"
            )
            params = {"cutoff": cutoff} if cond else {}
            if dry_run:
                n = (await db.execute(text(
                    f"SELECT count(*) FROM revoked_tokens WHERE {col} IS NOT NULL {cond}"
                ), params)).scalar()
            else:
                n = (await db.execute(text(sql), params)).rowcount
            if n:
                print(f"  revoked_tokens.{col}: {n} 行")
                total += n

        # 3. 病案首页快照 JSONB 里的 visit_time（ISO 字符串，签发时冻结的展示值）
        rows = (await db.execute(text(
            "SELECT id, patient_snapshot->>'visit_time' AS vt FROM medical_records "
            "WHERE patient_snapshot ? 'visit_time' "
            "AND patient_snapshot->>'visit_time' IS NOT NULL"
        ))).all()
        snap_fixed = 0
        for record_id, vt in rows:
            try:
                parsed = datetime.fromisoformat(vt)
            except ValueError:
                print(f"  [跳过] medical_records.{record_id} visit_time 无法解析: {vt}")
                continue
            if parsed > cutoff:
                continue  # 切换后签发的新快照已是北京时间
            shifted = (parsed + timedelta(hours=SHIFT_HOURS)).isoformat()
            if not dry_run:
                # cast(:v AS text) 而非 :v::text——"::"与 SQLAlchemy 具名参数解析冲突
                await db.execute(text(
                    "UPDATE medical_records SET patient_snapshot = "
                    "jsonb_set(patient_snapshot, '{visit_time}', to_jsonb(cast(:v AS text))) "
                    "WHERE id = :id"
                ), {"v": shifted, "id": record_id})
            snap_fixed += 1
        if snap_fixed:
            print(f"  medical_records.patient_snapshot.visit_time: {snap_fixed} 行")
            total += snap_fixed

        if dry_run:
            print(f"[dry-run] 共 {total} 行将被 +{SHIFT_HOURS}h，未写入")
            await db.rollback()
        else:
            await db.commit()
            print(f"[✓] 已提交：共 {total} 行 +{SHIFT_HOURS}h")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="存量 UTC 时间一次性校正为北京时间")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
