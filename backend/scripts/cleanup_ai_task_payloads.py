# -*- coding: utf-8 -*-
"""AI 任务载荷瘦身脚本（scripts/cleanup_ai_task_payloads.py，2026-08-28 全量体检）。

背景：ai_tasks 每次 LLM 调用插一行，input_snapshot/output_result 两个 JSONB
存整段输入输出全文——是库体积增长的绝对大头，此前无任何保留策略，
以年为单位单调膨胀并被每日备份反复携带。

瘦身口径（保守，只瘦不删）：
  超过保留期（默认 180 天，env AI_TASK_PAYLOAD_RETENTION_DAYS 可调）的行，
  把 input_snapshot/output_result 置 NULL；**行本身与全部元数据保留**
  （task_type/status/token_input/token_output/duration_ms/created_at），
  成本统计、用量分析、故障排查口径零影响。
  载荷的唯一在线消费方是工作台快照恢复（_encounter_snapshot 按接诊取最新
  一条建议回填）——接诊结束半年后不存在恢复场景，置空安全。

明确不动的表（需院方定保留政策后另做归档，别写进本脚本）：
  audit_logs   等保留痕 + 只追加触发器，技术上也删不动
  qc_reports / qc_issues / qc_reviews   病历质量证据链，体积远小于 ai_tasks
  record_versions   病历正文版本 + 签名哈希链，法定保留

部署方式（生产 ubuntu crontab，由 deploy.yml 自动配置）：
  20 4 * * * cd /app && docker compose exec -T backend \
      python scripts/cleanup_ai_task_payloads.py >> /var/log/mediscribe-voice-cleanup.log 2>&1

跑法（容器内）：
  python scripts/cleanup_ai_task_payloads.py             # 实际执行
  python scripts/cleanup_ai_task_payloads.py --dry-run   # 只统计不改
退出码：0 正常；非 0 有未处理异常（cron 日志可见 traceback）。
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, or_, select, update  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models.medical_record import AITask  # noqa: E402

DEFAULT_RETENTION_DAYS = 180


async def run(dry_run: bool) -> None:
    days = int(os.getenv("AI_TASK_PAYLOAD_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
    cutoff = datetime.now() - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        cond = (
            AITask.created_at < cutoff,
            or_(AITask.input_snapshot.isnot(None), AITask.output_result.isnot(None)),
        )
        n = (await db.execute(
            select(func.count()).select_from(AITask).where(*cond))).scalar() or 0
        if dry_run:
            print(f"[cleanup_ai_task_payloads] 干跑：{days} 天前含载荷的行 {n} 条（未修改）")
            return
        if n:
            await db.execute(update(AITask).where(*cond)
                             .values(input_snapshot=None, output_result=None))
            await db.commit()
        print(f"[cleanup_ai_task_payloads] {datetime.now():%F %T} "
              f"瘦身 {n} 行（保留期 {days} 天；行与 token 统计元数据不动）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ai_tasks 超期载荷瘦身（行保留，只清大字段）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不修改")
    asyncio.run(run(ap.parse_args().dry_run))
