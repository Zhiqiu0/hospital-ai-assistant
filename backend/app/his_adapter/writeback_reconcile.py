"""HIS 病历回写对账（his_adapter/writeback_reconcile.py）

2026-08-11 病历安全——第一版 HIS 对接的核心是病历回写，回写一旦静默失败，
病历就在 HIS 病案里缺失（合规问题），而原先既不自动重投、也不告警，全靠医生
自己刷叫号队列肉眼发现（真网已踩过 doctor_code 为空的坑）。

本模块提供后台对账：周期扫描「已签发但回写未成功」的 HIS 来源接诊，自动重投；
连续重投耗尽仍失败则记 error 日志（经 Sentry 上报告警），标记不再重试，避免刷屏。

状态记在 encounter.his_external_ref.writeback_records[record_type:record_no]
（2026-08-29 粒度下沉：每份文书各自一份状态，接诊级 writeback 只做队列展示）：
  status              : send_writeback 写入的最终状态（success/skipped/write_failed/...）
  reconcile_attempts  : 本对账任务对该文书累计重投次数
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
RECONCILE_WINDOW_DAYS = 3          # 只对账最近 3 天内**签发**的病历（更早的失败已人工介入）
MAX_RECONCILE_ATTEMPTS = 5         # 自动重投上限，超过报警并停手
SCAN_LIMIT = 200                   # 单轮最多处理条数，防一次扫太多
LOCK_TTL_SECONDS = RECONCILE_INTERVAL_SECONDS - 30   # 270s：锁 TTL
# 单轮处理截止余量（2026-08-13 第二轮审计修复）：单条回写最坏可达 180s
# （HTTP 写入/刷新各 3 次 × 30s 超时），只要 2 条走满超时就会超过锁 TTL——
# 锁中途过期后另一 worker 会对同一批候选并发重投，HIS 收到双份病历。
# 现在给每轮设截止时间：剩余时间不足一条最坏耗时就收工，剩下的下轮再做，
# 保证锁绝不会在处理途中过期。
ROUND_DEADLINE_MARGIN_SECONDS = 60

# 视为「回写未成功、需重投」的状态；success 是成功，skipped 是 WS/HTTP 都不在线
# （连接恢复后应重投，故也纳入对账）。
_RETRYABLE_STATUSES = {"skipped", "write_failed", "refresh_failed", "error"}


def _entry_key(rec: MedicalRecord) -> str:
    """文书级状态键（与 writeback_sender._record_key 同构）：record_type:record_no。"""
    return "{}:{}".format(
        rec.record_type or "",
        rec.record_no if rec.record_no is not None else "0",
    )


async def _find_candidates(db: AsyncSession) -> list[tuple[Encounter, MedicalRecord]]:
    """找出「已签发 + HIS 来源 + 该文书回写未成功且未耗尽」的 (接诊, 文书) 对。

    2026-08-29 粒度下沉：此前按接诊级 writeback.status 精筛，住院多文书时
    后一份的 success 覆盖前一份的失败，漏推的文书永远不会成为候选。
    现在逐份文书看 writeback_records[key]：缺失（从未推过/旧数据）或状态
    属可重试集且未耗尽，就把这份文书列为重投对象。旧接诊级状态只做展示，
    不再参与对账判定。（存量已成功的文书缺 per-record 键会被重推一次——
    回写按规范 §2.5 幂等覆盖，多推无害，还能顺带补上历史漏推。）

    JSONB 明细在 Python 侧过滤（SQLite 测试库不支持 .astext；生产候选量小）。
    """
    window_start = datetime.now() - timedelta(days=RECONCILE_WINDOW_DAYS)

    # 窗口卡在**病历签发时间**上，不是接诊开始时间（2026-08-14 第六轮审计修复）。
    #
    # 原先条件是 `Encounter.visited_at >= window_start`——接诊**开始**于 3 天内。
    # 门急诊当天接诊当天签发，两者差不多；但住院一次接诊长达十几天，
    # 病人第 5 天签发的病程，接诊早已在窗口外 → 对账根本扫不到它，
    # 回写失败后**永远不重投、也不告警**，而这正是对账存在的意义。
    # 回写该不该重投，取决于病历什么时候签发的，与接诊什么时候开始无关。
    submitted_enc_ids = select(MedicalRecord.encounter_id).where(
        MedicalRecord.status == "submitted",
        MedicalRecord.submitted_at >= window_start,
    )
    rows = (await db.execute(
        select(Encounter).where(
            Encounter.his_external_ref.isnot(None),
            Encounter.status != "cancelled",
            Encounter.id.in_(submitted_enc_ids),
        # LIMIT 不能加在这里（2026-08-13 第五轮审计修复）：粗筛只按"HIS 来源 +
        # 近窗口 + 有已签发病历"取，真正的"回写未成功"判定在下面的 Python 精筛。
        # 把 200 条上限压在精筛之前，等于按接诊时间截断——高峰期前 200 条里可能
        # 全是已回写成功的，真正需要重投的排在后面，永远轮不到，病历静默漏回写。
        # 改为按时间倒序多取一些，精筛后再截断。
        ).order_by(Encounter.visited_at.desc()).limit(SCAN_LIMIT * 10)
    )).scalars().all()

    his_encs = {enc.id: enc for enc in rows
                if (enc.his_external_ref or {}).get("source") == "admit_push"}
    if not his_encs:
        return []
    # 该批接诊的全部已签发文书（窗口内签发的才需要对账）
    recs = (await db.execute(
        select(MedicalRecord).where(
            MedicalRecord.encounter_id.in_(list(his_encs)),
            MedicalRecord.status == "submitted",
            MedicalRecord.submitted_at >= window_start,
        ).order_by(MedicalRecord.submitted_at.desc())
    )).scalars().all()

    candidates: list[tuple[Encounter, MedicalRecord]] = []
    for rec in recs:
        enc = his_encs[rec.encounter_id]
        wbr = (enc.his_external_ref or {}).get("writeback_records") or {}
        entry = wbr.get(_entry_key(rec)) or {}
        if entry.get("reconcile_exhausted"):
            continue
        status = entry.get("status")
        if status is None or status in _RETRYABLE_STATUSES:
            candidates.append((enc, rec))
        if len(candidates) >= SCAN_LIMIT:
            break   # 精筛后才截断，保证拿到的都是真正需要重投的
    return candidates


async def _reset_reconcile_attempts(
    db: AsyncSession, encounter_id: str, key: str,
) -> None:
    """把该文书的重投计数清零（HIS 整体离线：告警但不放弃，等对方恢复继续重试）。"""
    enc = await db.get(Encounter, encounter_id)
    if enc is None:
        return
    ref = dict(enc.his_external_ref or {})
    wbr = dict(ref.get("writeback_records") or {})
    entry = dict(wbr.get(key) or {})
    entry["reconcile_attempts"] = 0
    wbr[key] = entry
    ref["writeback_records"] = wbr
    enc.his_external_ref = ref
    await db.commit()


async def _mark_reconcile(
    db: AsyncSession, encounter_id: str, key: str, *, exhausted: bool,
) -> None:
    """累加该文书的重投次数；exhausted=True 标记放弃（JSONB 整体重赋值才被侦测为脏）。"""
    enc = await db.get(Encounter, encounter_id)
    if enc is None or not enc.his_external_ref:
        return
    ref = dict(enc.his_external_ref)
    wbr = dict(ref.get("writeback_records") or {})
    entry = dict(wbr.get(key) or {})
    entry["reconcile_attempts"] = int(entry.get("reconcile_attempts") or 0) + 1
    if exhausted:
        entry["reconcile_exhausted"] = True
    wbr[key] = entry
    ref["writeback_records"] = wbr
    enc.his_external_ref = ref
    await db.commit()


async def reconcile_once(deadline: float | None = None) -> int:
    """跑一轮对账：重投未成功的回写，返回本轮处理的条数。

    Args:
        deadline: asyncio 事件循环时刻（loop.time() 口径）。到点即收工，
            剩余候选留给下一轮——用于保证持锁时长不超过锁 TTL（见
            ROUND_DEADLINE_MARGIN_SECONDS 说明）。None=不限（单测用）。
    """
    from app.database import AsyncSessionLocal
    from app.his_adapter.writeback_sender import send_writeback

    async with AsyncSessionLocal() as db:
        candidates = await _find_candidates(db)

    processed = 0
    for enc, rec in candidates:
        if deadline is not None and asyncio.get_running_loop().time() >= deadline:
            logger.info("his_wb.reconcile: 触达本轮截止时间，剩余 %d 条留待下轮",
                        len(candidates) - processed)
            break
        key = _entry_key(rec)
        wb = ((enc.his_external_ref or {}).get("writeback_records") or {}).get(key) or {}
        attempts = int(wb.get("reconcile_attempts") or 0)
        if attempts >= MAX_RECONCILE_ATTEMPTS and wb.get("status") == "skipped":
            # 厂商整体离线不判"永久放弃"（2026-08-13 第五轮审计修复）：
            # skipped 的含义是"WS 与 HTTP 都不在线"，即 HIS 侧整体离线，
            # 跟"推过去但失败了"是两回事。原先它也照样触发 exhausted，
            # 于是 HIS 停机半小时（5 轮 × 5 分钟）就把全院当天病历统统标记成
            # 永久放弃——等 HIS 恢复也不会再补推，而这正是对账存在的全部意义。
            # 改为：照常告警（运维要知道 HIS 断了），但重置计数继续重试，
            # 等对方恢复自动补上。重试成本极低（5 分钟一轮、每轮上限 200 条）。
            logger.error(
                "his_wb.reconcile_offline: HIS 持续离线导致病历回写累计 %d 轮未送达，"
                "已告警但继续重试（不放弃）encounter=%s visit_no=%s record=%s",
                attempts, enc.id, enc.visit_no, key,
            )
            async with AsyncSessionLocal() as db:
                await _reset_reconcile_attempts(db, enc.id, key)
            continue
        if attempts >= MAX_RECONCILE_ATTEMPTS:
            # 达上限：记 error（Sentry 告警）+ 标记耗尽，停止自动重投
            logger.error(
                "his_wb.reconcile_exhausted: 病历回写连续 %d 次失败仍未成功，需人工处理 "
                "encounter=%s visit_no=%s record=%s status=%s",
                attempts, enc.id, enc.visit_no, key, wb.get("status"),
            )
            async with AsyncSessionLocal() as db:
                await _mark_reconcile(db, enc.id, key, exhausted=True)
            continue
        # 重投：send_writeback 会重新落库 writeback.status
        try:
            async with AsyncSessionLocal() as db:
                result = await send_writeback(db, enc.id, record_id=rec.id)
            # 只有失败才累计对账次数（2026-08-29 第五轮审计）：成功时 sender
            # 已把计数清零，这里再无条件 +1 会在 success 记录上残留
            # attempts=1，下次失败从 1 起算，5 次上限实际只剩 4 次。
            if not result.ok:
                async with AsyncSessionLocal() as db:
                    await _mark_reconcile(db, enc.id, key, exhausted=False)
            processed += 1
            logger.info("his_wb.reconcile: 重投 encounter=%s record=%s → %s",
                        enc.id, key, result.status)
        except Exception:
            logger.exception("his_wb.reconcile: 重投异常 encounter=%s record=%s",
                             enc.id, key)
    return processed


async def reconcile_loop() -> None:
    """回写对账常驻任务（main.py lifespan 启动，受 HIS 保险丝保护）。

    多 worker 防重：每轮先抢 Redis 锁，只让一个 worker 真正对账，避免两 worker
    同时重投同一接诊造成 HIS 双写。

    2026-08-13 第二轮审计修复两处：
      1. fail_open=False——生产是 2 worker（不是注释原先假设的单进程），
         Redis 挂时若 fail-open 两个 worker 会同时对账，双写进 HIS 病案。
         重复回写有对外副作用，宁可这轮不做。
      2. 单轮设截止时间——锁 TTL 270s 而单条最坏 180s，原先跑满就会锁中途
         过期、另一 worker 并发重投同一批。现在到点收工，锁绝不中途失效。
    """
    from app.services.redis_cache import redis_cache

    while True:
        try:
            await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)
            # 锁 TTL 略短于周期，正常单轮跑完自然释放；worker 崩溃也能到期自愈
            token = await redis_cache.acquire_lock(
                "his:wb:reconcile:lock", ttl=LOCK_TTL_SECONDS, fail_open=False
            )
            if token is None:
                continue  # 另一 worker 正在对账 / Redis 不可用 → 本轮跳过
            try:
                deadline = (asyncio.get_running_loop().time()
                            + LOCK_TTL_SECONDS - ROUND_DEADLINE_MARGIN_SECONDS)
                n = await reconcile_once(deadline=deadline)
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
