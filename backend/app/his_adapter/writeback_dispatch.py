"""回写派发（his_adapter/writeback_dispatch.py）

2026-08-11 业务联动冲刺：医生签发病历后自动回写 HIS，替代原先的手动端点。

为什么要「派发」而不是就地执行：
  生产 2 个 uvicorn worker，厂商 WS 长连接只挂在其中一个进程的 his_ws_manager
  里；签发请求（HTTP）可能落在另一个 worker——就地执行会误判「WS 未连接」。
  流程：
    1. 签发 worker 本地有 WS 连接 → 直接执行（最常见，单 worker 开发环境必走）
    2. 本地没有 → 经事件总线广播回写指令，各 worker 收到后「有连接者抢占执行」
       （来源诊室连接所在 worker 优先 0.5s，回写路由尽量回到原诊室）
    3. 广播后 3s 无人抢占（全院 WS 都断了）→ 本地兜底执行，走 HTTP 回落或
       skipped，把结果如实告知医生
  无论谁执行，结果都发布到医生的事件频道，工作台 SSE 弹「回写成功/失败」。

启动：main.py lifespan 里每个 worker 起一个 consumer_loop 常驻任务。
"""
import asyncio
import logging
import uuid

from app.his_adapter.event_bus import his_event_bus
from app.his_adapter.ws_manager import his_ws_manager

logger = logging.getLogger(__name__)

WB_CMD_CHANNEL = "his:wb:cmd"     # 回写指令广播频道（所有 worker 订阅）
CLAIM_TTL = 120                    # 抢占标记有效期（秒）：覆盖最坏 WS 重发耗时
CLAIM_WAIT_SECONDS = 3.0           # 派发方等待抢占的时长，超时本地兜底
PREFER_DELAY_SECONDS = 0.5         # 非来源诊室 worker 的让位延迟


async def dispatch_writeback(encounter_id: str, doctor_id: str, visit_no: str) -> None:
    """签发钩子入口（asyncio.create_task 调用，不阻塞签发响应）。

    Args:
        encounter_id: 接诊 ID
        doctor_id:    签发医生 ID（回写结果推送目标）
        visit_no:     就诊流水号（用于优先路由回来源诊室）
    """
    try:
        req_id = uuid.uuid4().hex
        if his_ws_manager.has_connection():
            # 本 worker 就有连接：直接执行（不广播，无重复执行风险）
            await _execute_and_report(encounter_id, doctor_id)
            return
        await his_event_bus.publish(WB_CMD_CHANNEL, {
            "req_id": req_id,
            "encounter_id": encounter_id,
            "doctor_id": doctor_id,
            "visit_no": visit_no,
        })
        await asyncio.sleep(CLAIM_WAIT_SECONDS)
        if not await his_event_bus.is_claimed(f"his:wb:claim:{req_id}"):
            # 没有任何 worker 持有 WS 连接：本地兜底（HTTP 回落或 skipped）
            logger.warning("his_wb.dispatch: 无 worker 抢占，本地兜底 encounter=%s",
                           encounter_id)
            await _execute_and_report(encounter_id, doctor_id)
    except Exception:
        # 后台任务的异常没人 await，必须自己兜住记日志，绝不静默丢
        logger.exception("his_wb.dispatch: 派发异常 encounter=%s", encounter_id)


async def consumer_loop() -> None:
    """回写指令消费循环（每个 worker 一个常驻任务，main.py lifespan 启动）。"""
    while True:
        try:
            async with his_event_bus.subscription(WB_CMD_CHANNEL) as q:
                while True:
                    cmd = await q.get()
                    # 每条指令独立任务处理，慢回写不阻塞后续指令
                    asyncio.create_task(_maybe_execute(cmd))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("his_wb.consumer: 订阅循环异常，5s 后重建")
            await asyncio.sleep(5)


async def _maybe_execute(cmd: dict) -> None:
    """收到回写指令：有 WS 连接才参与抢占，来源诊室所在 worker 优先。"""
    try:
        if not his_ws_manager.has_connection():
            return  # 本 worker 没有厂商连接，让位
        visit_no = str(cmd.get("visit_no") or "")
        if visit_no and not his_ws_manager.has_visit(visit_no):
            # 不是来源诊室所在 worker：稍让 0.5s，让来源 worker 先抢
            await asyncio.sleep(PREFER_DELAY_SECONDS)
        if not await his_event_bus.try_claim(
            f"his:wb:claim:{cmd.get('req_id', '')}", CLAIM_TTL
        ):
            return  # 别的 worker 已抢到
        await _execute_and_report(str(cmd.get("encounter_id", "")),
                                  str(cmd.get("doctor_id", "")))
    except Exception:
        logger.exception("his_wb.consumer: 指令处理异常 cmd=%s", cmd.get("req_id"))


async def _execute_and_report(encounter_id: str, doctor_id: str) -> None:
    """执行回写并把结果发布到医生事件频道（SSE 弹提示）。"""
    from app.database import AsyncSessionLocal
    from app.his_adapter.writeback_sender import send_writeback

    try:
        async with AsyncSessionLocal() as db:
            result = await send_writeback(db, encounter_id)
        ok, status, message = result.ok, result.status, result.message
    except Exception as exc:
        logger.exception("his_wb.execute: 回写异常 encounter=%s", encounter_id)
        ok, status, message = False, "error", str(exc)

    logger.info("his_wb.execute: encounter=%s status=%s ok=%s", encounter_id, status, ok)
    await his_event_bus.publish(f"his:doctor:{doctor_id}", {
        "type": "writeback_result",
        "encounter_id": encounter_id,
        "ok": ok,
        "status": status,   # success / skipped / write_failed / refresh_failed / error
        "message": message,
    })
