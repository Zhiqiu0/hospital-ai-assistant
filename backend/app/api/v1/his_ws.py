"""HIS WebSocket 通道路由（接口规范 v1.1 第 7 章，方案 B）：/api/v1/his/ws

职责：握手验签 → 接入连接管理器 → 消息循环（分发 ping/ack/接诊推送）→ 心跳与空闲超时。
上行消息我方强制验签；下行（回写/刷新）由 writeback_sender 经 ws_manager 发出。
不挂 require_his_enabled 依赖（那是 HTTP 语义的 503），保险丝在握手处手动检查。
"""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import settings
from app.his_adapter import ws_protocol as wp
from app.his_adapter.models import AdmitPushRequest
from app.his_adapter.ws_manager import his_ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/his", tags=["HIS对接"])


@router.websocket("/ws")
async def his_ws_endpoint(websocket: WebSocket) -> None:
    """HIS 长连接入口：握手验签不过直接拒绝，验签通过后进入消息循环。"""
    # 保险丝：HIS 对接开关关闭时拒绝握手（accept 之前 close = 拒绝升级）
    if not settings.his_adapter_enabled:
        await websocket.close(code=4403)
        return
    q = websocket.query_params
    err = wp.verify_handshake(
        q.get("app_id", ""), q.get("timestamp", ""), q.get("nonce", ""),
        q.get("sign", ""), settings.his_inbound_app_id,
        settings.his_inbound_app_secret, settings.his_sign_clock_skew_seconds,
    )
    if err is not None:
        logger.warning("his_ws.handshake_rejected: %s client=%s", err, websocket.client)
        await websocket.close(code=4401)
        return

    # 握手防重放（2026-08-11 审计延期项）：验签通过后一次性 claim 握手 nonce，
    # 拦截时间窗内重放同一握手 URL 建连（截收病历回写）。TTL=时钟偏差窗口+60s 缓冲，
    # 超窗后 timestamp_fresh 已会拒。Redis 不可用时 claim_nonce fail-open，退化为仅
    # 靠时间戳窗口兜底（与上行消息 nonce 同哲学）。
    from app.services.redis_cache import redis_cache
    if not await redis_cache.claim_nonce(
        "his_ws_handshake", q.get("nonce", ""),
        ttl=settings.his_sign_clock_skew_seconds + 60,
    ):
        logger.warning("his_ws.handshake_replay: nonce 重复，拒绝建连 client=%s",
                       websocket.client)
        await websocket.close(code=4401)
        return

    await websocket.accept()
    his_ws_manager.register(websocket)  # 每台诊室客户端各一条连接，多条并存
    logger.info("his_ws.connected: client=%s", websocket.client)
    ping_task = asyncio.create_task(_ping_loop(websocket))
    try:
        while True:
            # 空闲超时（规范 7.4）：90s 未收到任何消息判定连接失效
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=wp.IDLE_TIMEOUT
            )
            await _handle_message(websocket, raw)
    except asyncio.TimeoutError:
        logger.warning("his_ws.idle_timeout: 90s 无消息，关闭连接")
        try:
            await websocket.close()
        except Exception:
            pass
    except WebSocketDisconnect:
        logger.info("his_ws.disconnected: client=%s", websocket.client)
    except Exception as exc:  # 连接层意外错误：记日志后走统一清理
        logger.warning("his_ws.connection_error: %s", exc)
    finally:
        ping_task.cancel()
        his_ws_manager.unregister(websocket)


async def _ping_loop(websocket: WebSocket) -> None:
    """心跳任务（规范 7.4）：每 30s 发一次 ping；发送失败即退出（连接已死）。"""
    aid, secret = settings.his_inbound_app_id, settings.his_inbound_app_secret
    try:
        while True:
            await asyncio.sleep(wp.HEARTBEAT_INTERVAL)
            await websocket.send_text(
                wp.build_signed_message(wp.MSG_PING, {}, aid, secret)
            )
    except (asyncio.CancelledError, Exception):
        return


async def _handle_message(websocket: WebSocket, raw: str) -> None:
    """单条上行消息分发：ping/pong 免验签，ack 与业务消息强制验签。"""
    aid, secret = settings.his_inbound_app_id, settings.his_inbound_app_secret
    try:
        env = wp.WsEnvelope.model_validate_json(raw)
    except ValidationError:
        logger.warning("his_ws.bad_envelope: 信封不合法，丢弃")  # 无 msg_id 可回 ack
        return

    if env.type == wp.MSG_PING:  # 厂商侧心跳 → 立即回 pong
        await websocket.send_text(
            wp.build_signed_message(wp.MSG_PONG, {}, aid, secret)
        )
        return
    if env.type == wp.MSG_PONG:  # 我方 ping 的回应，收到即已刷新空闲计时
        return

    payload_raw = wp.extract_payload_raw(raw, env.payload)
    code = wp.verify_message(
        env, payload_raw, aid, secret, settings.his_sign_clock_skew_seconds
    )

    if env.type == wp.MSG_ACK:
        # 厂商对我方下行消息的应答：验签通过才转给 manager，不通过丢弃（不回 ack 的 ack）
        if code is None:
            matched = his_ws_manager.resolve_ack(
                str(env.payload.get("ack_msg_id", "")), env.payload
            )
            if not matched:
                logger.warning("his_ws.orphan_ack: ack_msg_id=%s 无等待方",
                               env.payload.get("ack_msg_id"))
        else:
            logger.warning("his_ws.ack_verify_failed: code=%s 丢弃", code)
        return

    if code is not None:  # 业务消息验签失败 → 按 2.4 错误码回 ack
        await websocket.send_text(
            wp.build_ack(env.msg_id, code, wp.ERROR_TEXT[code], aid, secret)
        )
        return

    if env.type == wp.MSG_ADMIT:
        await _handle_admit(websocket, env, aid, secret)
    else:
        await websocket.send_text(
            wp.build_ack(env.msg_id, 40004, "未知消息类型", aid, secret)
        )


async def _handle_admit(
    websocket: WebSocket, env: wp.WsEnvelope, aid: str, secret: str
) -> None:
    """接诊推送处理：msg_id 幂等去重 + 载荷校验 + 业务落地 + ack。

    业务落地（2026-08-11 联动冲刺）由 admit_service.handle_admit 完成：
    患者自动建档 + 按工号派医生 + visit_id 幂等建接诊 + 发工作台叫号事件。
    """
    from app.his_adapter import admit_service
    from app.services.redis_cache import redis_cache

    # 重发去重（规范 7.4）：厂商超时重发用同 msg_id，已处理过则幂等地再回成功 ack
    first_time = await redis_cache.claim_nonce(
        "his_ws_msg", env.msg_id, ttl=600
    )
    if not first_time:
        await websocket.send_text(
            wp.build_ack(env.msg_id, 0, "重复消息，此前已处理", aid, secret,
                         data={"visit_id": env.payload.get("visit_id", "")})
        )
        return
    # 失败释放 msg_id 去重占位（2026-08-11 审计修复）：claim_nonce 是「先占后处理」，
    # 若处理失败仍占着 key，厂商按规范 7.4 超时重发同 msg_id 会命中上面的重复分支拿到
    # 假成功 ack（患者其实没落库）。故所有失败分支在回错误 ack 前显式释放占位，
    # 让重发能真正重新处理（handle_admit 本身按 visit_id 幂等，重入也不会建重）。
    async def _release_and_ack(code: int, message: str) -> None:
        await redis_cache.delete(f"nonce:his_ws_msg:{env.msg_id}")
        await websocket.send_text(wp.build_ack(env.msg_id, code, message, aid, secret))

    try:
        payload = AdmitPushRequest.model_validate(env.payload)
    except ValidationError:
        await _release_and_ack(40004, wp.ERROR_TEXT[40004])
        return
    # 记录该就诊的来源连接：回写/刷新优先路由回这台诊室（它的界面才需要刷新）
    his_ws_manager.bind_visit(payload.visit_id, websocket)
    try:
        result = await admit_service.handle_admit(payload)
    except admit_service.AdmitError as exc:
        # 业务拒收（如医生工号未注册）：错误码回 ack，厂商日志可见、便于排查
        logger.warning("his_ws.admit_rejected: visit_id=%s %s",
                       payload.visit_id, exc.message)
        await _release_and_ack(exc.code, exc.message)
        return
    except Exception:
        logger.exception("his_ws.admit_error: visit_id=%s", payload.visit_id)
        await _release_and_ack(50000, "服务内部错误")
        return
    logger.info("his_ws.admit: visit_id=%s patient=%s encounter=%s reused=%s",
                payload.visit_id, payload.patient_name,
                result.encounter_id, result.reused)
    await websocket.send_text(
        wp.build_ack(env.msg_id, 0, "success", aid, secret,
                     data={"visit_id": payload.visit_id,
                           "encounter_id": result.encounter_id})
    )
