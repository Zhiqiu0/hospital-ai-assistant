"""AI 供应商余额预警（上线前体检 2026-08-16 新增）。

**为什么需要**：AI 余额耗尽是全院级单点——不是某个医生某次生成失败，而是
**所有医生的所有 AI 功能同时停摆**，而且没有任何前兆。体检当天实测：
生产账户余额 5.85 元，按真实用量（每次接诊约 9200 输入 + 3300 输出 token）
折算只够约 130 次接诊，40 位医生上线后撑不到半天。

**为什么不塞进 /health/deep**：那个端点被容器 liveness 与 uptime-kuma 用着，
余额低就让健康检查失败会触发重启，把「该充值了」变成「服务反复重启」，
比问题本身更糟。余额低是**业务预警**不是**服务故障**，两者必须分开。

做法：低于阈值时记 error 日志 → 经 Sentry 告警（已接入）。
查询失败一律静默降级——供应商没有这个接口、或换了厂商，都不该影响主流程。
"""
import asyncio
import logging

import httpx

from app.config import settings
from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 6 * 3600   # 每 6 小时查一次（余额变化慢，够用且不扰民）
WARN_THRESHOLD_CNY = 100.0          # 低于此值告警：按现价约 1300 次接诊的余量
BALANCE_URL = "https://api.deepseek.com/user/balance"
# 多 worker 单实例锁的键（见 balance_monitor_loop 里的说明）
_MONITOR_LOCK_KEY = "ai:balance:monitor:lock"
# 每次接诊估算成本（元）。按 DeepSeek 2026-08 价目 × 实测用量（约 9200 输入
# + 3300 输出 token/接诊）折算 ≈ 0.076 元。价目调整时同步更新此数——
# 2026-08-29 对抗复核发现旧值 0.045 用的是降价前价目，剩余次数虚高近一倍。
COST_PER_ENCOUNTER_CNY = 0.076


async def check_balance_once() -> float | None:
    """查一次余额；返回人民币余额，查不到返回 None（不抛异常）。"""
    if not settings.deepseek_api_key:
        return None
    # 仅对 DeepSeek 官方端点有效；换供应商时静默跳过而不是报错
    if "deepseek.com" not in (settings.deepseek_base_url or ""):
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                BALANCE_URL,
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            )
        if resp.status_code != 200:
            logger.warning("ai_balance: 查询失败 HTTP %s", resp.status_code)
            return None
        data = resp.json()
        for info in data.get("balance_infos", []):
            if info.get("currency") == "CNY":
                return float(info.get("total_balance", 0))
        return None
    except Exception as exc:
        # 网络抖动/接口变更都不该影响业务，只留痕
        logger.warning("ai_balance: 查询异常 %s", exc)
        return None


async def balance_monitor_loop() -> None:
    """余额预警常驻任务（main.py lifespan 启动）。

    只记日志不做任何拦截——余额不足时医生该照常用到最后一刻，
    而不是被我方提前掐断。
    """
    while True:
        try:
            # 单实例保护（2026-09-02 可观测性专项）：生产用 --workers 2，
            # 每个 worker 的 lifespan 都会起一个本任务，于是同一次余额告警在
            # error.log 与 Sentry 里各出现两条。同目录的另两个常驻任务
            # （writeback_dispatch 用 SET NX 抢占、writeback_reconcile 用
            # acquire_lock）早就处理了这件事，只有本任务漏了。
            # 锁 TTL 取检查间隔的一半：够长到能挡住同一轮的另一个 worker，
            # 又短到进程崩溃后下一轮仍能接上。
            if not await redis_cache.acquire_lock(
                _MONITOR_LOCK_KEY, ttl=CHECK_INTERVAL_SECONDS // 2
            ):
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                continue
            balance = await check_balance_once()
            if balance is None:
                pass  # 查不到就跳过本轮，原因已在 check_balance_once 里记过
            elif balance < WARN_THRESHOLD_CNY:
                # error 级 → Sentry 告警。文案写清「会怎样」，
                # 免得看到告警的人不知道这条有多急。
                logger.error(
                    "ai_balance_low: AI 供应商余额仅剩 %.2f 元（阈值 %.0f）。"
                    "按每次接诊约 %.3f 元估算，约还能支撑 %d 次接诊；"
                    "耗尽后全院 AI 生成/质控会同时失败，请尽快充值。",
                    balance, WARN_THRESHOLD_CNY, COST_PER_ENCOUNTER_CNY,
                    int(balance / COST_PER_ENCOUNTER_CNY),
                )
            else:
                logger.info("ai_balance: 余额 %.2f 元，充足", balance)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ai_balance: 预警轮异常")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
