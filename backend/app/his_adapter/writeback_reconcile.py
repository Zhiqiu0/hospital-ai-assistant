"""HIS 病历回写对账（his_adapter/writeback_reconcile.py）

2026-08-11 病历安全——第一版 HIS 对接的核心是病历回写，回写一旦静默失败，
病历就在 HIS 病案里缺失（合规问题），而原先既不自动重投、也不告警，全靠医生
自己刷叫号队列肉眼发现（真网已踩过 doctor_code 为空的坑）。

本模块提供后台对账：周期扫描「已签发但回写未成功」的 HIS 来源接诊，自动重投；
连续重投耗尽仍失败则记 error 日志（经 Sentry 上报告警），标记不再重试，避免刷屏。

状态记在 encounter.his_external_ref.writeback：
  status              : send_writeback 写入的最终状态（success/skipped/write_failed/...）
  reconcile_attempts  : 本对账任务累计重投次数
  reconcile_exhausted : True 表示已达上限、放弃自动重投（待人工处理）

调用：main.py lifespan 起 reconcile_loop 常驻任务（受 HIS 保险丝保护）。
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 300   # 对账周期：每 5 分钟扫一次
RECONCILE_WINDOW_DAYS = 3          # 只对账最近 3 天的接诊（更早的失败已人工介入）
MAX_RECONCILE_ATTEMPTS = 5         # 自动重投上限，超过报警并停手
SCAN_LIMIT = 200                   # 单轮最多处理条数，防一次扫太多

# 视为「回写未成功、需重投」的状态；success 是成功，skipped 是 WS/HTTP 都不在线
# （连接恢复后应重投，故也纳入对账）。
_RETRYABLE_STATUSES = {"skipped", "write_failed", "refresh_failed", "error"}


async def _find_candidates(db: AsyncSession) -> list[Encounter]:
    """找出「已签发 + HIS 来源 + 回写未成功且未耗尽」的接诊。

    JSONB 明细在 Python 侧过滤（SQLite 测试库不支持 .astext；生产候选量小）。
    先用 SQL 粗筛（HIS 来源、近窗口、有已签发病历），再 Python 精筛回写状态。
    """
    window_start = datetime.now() - timedelta(days=RECONCILE_WINDOW_DAYS)
    submitted_enc_ids = select(MedicalRecord.encounter_id).where(
        MedicalRecord.status == "submitted"
    )
    rows = (await db.execute(
        select(Encounter).where(
            Encounter.his_external_ref.isnot(None),
            Encounter.visited_at >= window_start,
            Encounter.status != "cancelled",
            Encounter.id.in_(submitted_enc_ids),
        ).limit(SCAN_LIMIT)
    )).scalars().all()

    candidates = []
    for enc in rows:
        ref = enc.his_external_ref or {}
        if ref.get("source") != "admit_push":
            continue
        wb = ref.get("writeback") or {}
        # 从未回写过（无 writeback 键）或状态属可重试集，且未标记耗尽
        status = wb.get("status")
        if wb.get("reconcile_exhausted"):
            continue
        if status is None or status in _RETRYABLE_STATUSES:
            candidates.append(enc)
    return candidates


async def _mark_reconcile(db: AsyncSession, encounter_id: str, *, exhausted: bool) -> None:
    """累加重投次数；exhausted=True 时标记放弃（JSONB 整体重赋值才被侦测为脏）。"""
    enc = await db.get(Encounter, encounter_id)
    if enc is None or not enc.his_external_ref:
        return
    ref = dict(enc.his_external_ref)
    wb = dict(ref.get("writeback") or {})
    wb["reconcile_attempts"] = int(wb.get("reconcile_attempts") or 0) + 1
    if exhausted:
        wb["reconcile_exhausted"] = True
    ref["writeback"] = wb
    enc.his_external_ref = ref
    await db.commit()


async def reconcile_once() -> int:
    """跑一轮对账：重投未成功的回写，返回本轮处理的条数。"""
    from app.database import AsyncSessionLocal
    from app.his_adapter.writeback_sender import send_writeback

    async with AsyncSessionLocal() as db:
        candidates = await _find_candidates(db)

    processed = 0
    for enc in candidates:
        wb = (enc.his_external_ref or {}).get("writeback") or {}
        attempts = int(wb.get("reconcile_attempts") or 0)
        if attempts >= MAX_RECONCILE_ATTEMPTS:
            # 达上限：记 error（Sentry 告警）+ 标记耗尽，停止自动重投
            logger.error(
                "his_wb.reconcile_exhausted: 病历回写连续 %d 次失败仍未成功，需人工处理 "
                "encounter=%s visit_no=%s status=%s",
                attempts, enc.id, enc.visit_no, wb.get("status"),
            )
            async with AsyncSessionLocal() as db:
                await _mark_reconcile(db, enc.id, exhausted=True)
            continue
        # 重投：send_writeback 会重新落库 writeback.status
        try:
            async with AsyncSessionLocal() as db:
                result = await send_writeback(db, enc.id)
            async with AsyncSessionLocal() as db:
                await _mark_reconcile(db, enc.id, exhausted=False)
            processed += 1
            logger.info("his_wb.reconcile: 重投 encounter=%s → %s",
                        enc.id, result.status)
        except Exception:
            logger.exception("his_wb.reconcile: 重投异常 encounter=%s", enc.id)
    return processed


async def reconcile_loop() -> None:
    """回写对账常驻任务（main.py lifespan 启动，受 HIS 保险丝保护）。

    多 worker 防重：每轮先抢 Redis 锁，只让一个 worker 真正对账，避免两 worker
    同时重投同一接诊造成 HIS 双写。Redis 不可用时锁恒成功（单进程无并发）。
    """
    from app.services.redis_cache import redis_cache

    while True:
        try:
            await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)
            # 锁 TTL 略短于周期，正常单轮跑完自然释放；worker 崩溃也能到期自愈
            token = await redis_cache.acquire_lock(
                "his:wb:reconcile:lock", ttl=RECONCILE_INTERVAL_SECONDS - 30
            )
            if token is None:
                continue  # 另一 worker 正在对账，本轮跳过
            try:
                n = await reconcile_once()
                if n:
                    logger.info("his_wb.reconcile: 本轮重投 %d 条", n)
            finally:
                try:
                    await redis_cache.release_lock("his:wb:reconcile:lock", token)
                except Exception:
                    pass  # 释放失败靠 TTL 到期兜底
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("his_wb.reconcile: 对账轮异常，下一周期重试")
