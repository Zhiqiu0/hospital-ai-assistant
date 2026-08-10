"""HIS WebSocket 连接管理（多连接版：每台诊室客户端各一条，2026-08 定稿拓扑）。

拓扑决策：厂商 HIS 为客户端直连数据库的 C/S 架构，WS 代码加在全科客户端里，
故同一机构会有多条并发连接（每诊室一条）。路由规则：
  - 接诊推送：任意连接进来都收；
  - 回写/刷新：优先发回「该就诊的接诊推送来源连接」（那台诊室的界面才需要刷新），
    来源连接已断则退回任一在线连接（写库任何客户端都能干，刷新由医生重开页面兜底）。
"""
import asyncio
import logging
import uuid

from app.his_adapter import ws_protocol as wp

logger = logging.getLogger(__name__)

# visit→连接 映射的容量上限：只为回写路由服务，超出后淘汰最老的（dict 保序）
VISIT_MAP_MAX = 500


class HisWsManager:
    """多连接管理：注册/注销、visit 来源绑定、下行消息按 visit 路由并等 ack。"""

    def __init__(self):
        self._conns: list = []  # 当前所有活跃连接（starlette WebSocket）
        self._pending: dict[str, tuple[asyncio.Future, object]] = {}  # msg_id → (future, ws)
        self._visit_conn: dict[str, object] = {}  # visit_id → 接诊来源连接

    def register(self, websocket) -> None:
        """新连接接入（多诊室并存，不互相顶替）。"""
        self._conns.append(websocket)

    def unregister(self, websocket) -> None:
        """连接断开：只清理属于该连接的 future 与 visit 绑定，不影响其他诊室。"""
        if websocket in self._conns:
            self._conns.remove(websocket)
        for msg_id in [m for m, (_, w) in self._pending.items() if w is websocket]:
            fut, _ = self._pending.pop(msg_id)
            if not fut.done():
                fut.set_exception(ConnectionError("HIS WebSocket 连接已断开"))
        for visit_id in [v for v, w in self._visit_conn.items() if w is websocket]:
            del self._visit_conn[visit_id]

    def has_connection(self) -> bool:
        """回写发送方据此选通道：任一诊室在线即走 WS。"""
        return bool(self._conns)

    def bind_visit(self, visit_id: str, websocket) -> None:
        """接诊推送到达时记录来源连接，回写时优先路由回同一台诊室。"""
        self._visit_conn.pop(visit_id, None)  # 重复推送以最新来源为准
        self._visit_conn[visit_id] = websocket
        while len(self._visit_conn) > VISIT_MAP_MAX:  # 淘汰最老绑定，防无限增长
            self._visit_conn.pop(next(iter(self._visit_conn)))

    def _pick(self, prefer_visit: str) -> object:
        """选发送连接：该就诊的来源连接在线则用它，否则任一在线连接。"""
        ws = self._visit_conn.get(prefer_visit)
        if ws is not None and ws in self._conns:
            return ws
        return self._conns[0]

    def resolve_ack(self, ack_msg_id: str, payload: dict) -> bool:
        """路由层收到厂商 ack 时调用；返回是否匹配到等待中的下行消息。"""
        entry = self._pending.pop(ack_msg_id, None)
        if entry is not None and not entry[0].done():
            entry[0].set_result(payload)
            return True
        return False

    async def send_with_ack(
        self, msg_type: str, payload: dict, app_id: str, secret: str,
        prefer_visit: str = "",
    ) -> dict:
        """发送下行业务消息并等 ack（规范 7.4：10s 超时重发同 msg_id，最多 3 次）。

        Returns:
            ack 的 payload（业务成败由调用方看 code）
        Raises:
            ConnectionError: 无连接 / 发送失败 / 重发耗尽（仅关闭出问题的那条连接）
        """
        if not self._conns:
            raise ConnectionError("HIS WebSocket 未连接")
        ws = self._pick(prefer_visit)
        msg_id = f"ms-{uuid.uuid4().hex}"
        for attempt in range(1 + wp.ACK_MAX_RESEND):
            # 重发 msg_id 不变，timestamp/nonce/sign 重新生成（同 2.2 重试规则）
            text = wp.build_signed_message(msg_type, payload, app_id, secret, msg_id=msg_id)
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[msg_id] = (fut, ws)
            try:
                await ws.send_text(text)
                return await asyncio.wait_for(fut, timeout=wp.ACK_TIMEOUT)
            except asyncio.TimeoutError:
                self._pending.pop(msg_id, None)
                logger.warning("his_ws.ack_timeout: type=%s msg_id=%s attempt=%d",
                               msg_type, msg_id, attempt + 1)
            except ConnectionError:
                raise  # unregister 触发的断线异常，原样上抛
            except Exception as exc:  # 发送失败 = 该连接半死，按断线处理
                self._pending.pop(msg_id, None)
                raise ConnectionError(f"发送失败：{exc}") from exc
        # 重发耗尽：按规范 7.4 判定该连接失效，关闭并清理（其余诊室连接不受影响）
        try:
            await ws.close()
        except Exception:
            pass  # 关闭失败不影响清理
        self.unregister(ws)
        raise ConnectionError("ack 超时重发耗尽，连接判定失效")


# 全局单例（路由层与回写发送方共用）
his_ws_manager = HisWsManager()
