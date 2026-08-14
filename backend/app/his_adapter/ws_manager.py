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

    def has_visit(self, visit_id: str) -> bool:
        """该就诊的来源连接是否在本进程且在线（回写派发的 worker 优先级判断用）。"""
        ws = self._visit_conn.get(visit_id)
        return ws is not None and ws in self._conns

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

        僵尸连接换线（2026-08-13 第二轮审计修复）：网络闪断后的连接要到 90s
        空闲超时才会被摘除，期间仍可能被 _pick 选中（尤其它是来源诊室连接时），
        回写在它身上空耗 40s 后直接报失败——即使院内还有其他在线诊室连接。
        现在一条连接判定失效后自动换下一条重试，全部失效才算失败。

        Returns:
            ack 的 payload（业务成败由调用方看 code）
        Raises:
            ConnectionError: 无连接 / 所有在线连接都发送失败或 ack 耗尽
        """
        if not self._conns:
            raise ConnectionError("HIS WebSocket 未连接")
        first = self._pick(prefer_visit)
        # 候选顺序：优先来源诊室连接，其余作为换线兜底
        candidates = [first] + [c for c in self._conns if c is not first]
        last_exc: Exception | None = None
        # ── msg_id 在这里生成，换线时**不变**（2026-08-14 第八轮审计）─────────
        #
        # 原先 msg_id 生成在 _send_once_with_ack 内部，于是「重发 msg_id 不变」
        # 这句承诺只在同一条连接的 3 次重发内成立，换线就换了个新 msg_id。
        # 真实故障形态：来源诊室连接是「半死」的（TCP 未断、全科客户端其实
        # 已经收到 writeback 并写进了 HIS，只是 ack 因卡顿/单向丢包没回来），
        # 我方 10s×3 判失效后换线重发——同一份病历以两个不同 msg_id 下发两次，
        # 厂商无法按 msg_id 判重，HIS 病案里就多出一份，而医生侧显示的是一次成功。
        # msg_id 正是本协议约定的幂等键：我方处理厂商上行 admit 时就是用它去重
        # （his_ws.py 的 claim_nonce），下行方向没有理由不一致。
        msg_id = f"ms-{uuid.uuid4().hex}"
        for idx, conn in enumerate(candidates):
            if conn not in self._conns:
                continue  # 期间已被摘除（其他协程判定失效）
            try:
                return await self._send_once_with_ack(
                    conn, msg_type, payload, app_id, secret, msg_id=msg_id)
            except ConnectionError as exc:
                last_exc = exc
                if idx + 1 < len(candidates):
                    logger.warning("his_ws.failover: 连接失效，换下一条重试 type=%s",
                                   msg_type)
        raise last_exc or ConnectionError("HIS WebSocket 未连接")

    async def _send_once_with_ack(
        self, ws: object, msg_type: str, payload: dict, app_id: str, secret: str,
        *, msg_id: str,
    ) -> dict:
        """在指定连接上发送并等 ack；该连接判定失效时关闭+摘除并抛 ConnectionError。

        msg_id 由调用方（send_with_ack）传入并在**换线时保持不变**——它是本协议
        约定的幂等键，同一份病历无论换几条连接重投都必须是同一个值，
        否则厂商无法判重、HIS 病案里会多出一份病历（第八轮审计）。
        """
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
                # 顺手摘除（2026-08-13）：发送失败是连接已死的确定信号，不摘掉
                # 会让它继续被 _pick 选中，后续回写反复空耗。
                self.unregister(ws)
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
