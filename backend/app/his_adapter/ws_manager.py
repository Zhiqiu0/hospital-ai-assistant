"""HIS WebSocket 连接管理（规范 7.2：一家机构一条连接）。

持有当前 HIS 长连接引用 + 下行消息「等 ack」的 future 表；
回写发送方（writeback_sender）通过全局单例 his_ws_manager 走长连接下发。
"""
import asyncio
import logging
import uuid

from app.his_adapter import ws_protocol as wp

logger = logging.getLogger(__name__)


class HisWsManager:
    """单连接管理器：注册/注销连接、下行消息发送并等 ack（超时重发）。"""

    def __init__(self):
        self._ws = None  # 当前活跃的 starlette WebSocket；None = 未连接
        self._pending: dict[str, asyncio.Future] = {}  # msg_id → 等 ack 的 future

    def register(self, websocket) -> None:
        """新连接接入（顶替旧引用；旧连接的关闭由路由层处理）。"""
        self._ws = websocket

    def unregister(self, websocket) -> None:
        """连接断开时清理。只清理自己的引用，防止旧连接晚到的清理误伤新连接。"""
        if self._ws is websocket:
            self._ws = None
        # 断线后所有等 ack 的下行消息立即失败，由调用方决定后续（如回落 HTTP）
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError("HIS WebSocket 连接已断开"))
        self._pending.clear()

    def has_connection(self) -> bool:
        """回写发送方据此选择通道：True 走长连接（方案 B），False 回落 HTTP。"""
        return self._ws is not None

    def resolve_ack(self, ack_msg_id: str, payload: dict) -> bool:
        """路由层收到厂商 ack 时调用；返回是否匹配到等待中的下行消息。"""
        fut = self._pending.pop(ack_msg_id, None)
        if fut is not None and not fut.done():
            fut.set_result(payload)
            return True
        return False

    async def send_with_ack(
        self, msg_type: str, payload: dict, app_id: str, secret: str
    ) -> dict:
        """发送下行业务消息并等 ack（规范 7.4：10s 超时重发同 msg_id，最多 3 次）。

        Returns:
            ack 的 payload（含 code/message/data，业务成败由调用方看 code）
        Raises:
            ConnectionError: 未连接 / 发送失败 / 重发耗尽（连接会被主动关闭）
        """
        if self._ws is None:
            raise ConnectionError("HIS WebSocket 未连接")
        msg_id = f"ms-{uuid.uuid4().hex}"
        for attempt in range(1 + wp.ACK_MAX_RESEND):
            # 每次重发 msg_id 不变，但 timestamp/nonce/sign 重新生成（同 2.2 重试规则）
            text = wp.build_signed_message(msg_type, payload, app_id, secret, msg_id=msg_id)
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[msg_id] = fut
            try:
                await self._ws.send_text(text)
                return await asyncio.wait_for(fut, timeout=wp.ACK_TIMEOUT)
            except asyncio.TimeoutError:
                self._pending.pop(msg_id, None)
                logger.warning(
                    "his_ws.ack_timeout: type=%s msg_id=%s attempt=%d",
                    msg_type, msg_id, attempt + 1,
                )
            except ConnectionError:
                raise  # unregister 触发的断线异常，原样上抛
            except Exception as exc:  # 发送失败 = 连接半死，按断线处理
                self._pending.pop(msg_id, None)
                raise ConnectionError(f"发送失败：{exc}") from exc
        # 重发耗尽：按规范 7.4 判定连接失效，主动关闭并清理
        dead_ws = self._ws
        try:
            await dead_ws.close()
        except Exception:
            pass  # 关闭失败不影响清理
        self.unregister(dead_ws)
        raise ConnectionError("ack 超时重发耗尽，连接判定失效")


# 全局单例（路由层与回写发送方共用）
his_ws_manager = HisWsManager()
