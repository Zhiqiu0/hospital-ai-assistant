"""HIS 业务联动事件总线（his_adapter/event_bus.py）

为什么需要它（2026-08-11 业务联动冲刺）：
  生产 uvicorn 跑 2 个 worker（entrypoint.sh），而厂商 WS 长连接、医生工作台的
  SSE 队列连接、签发病历的 HTTP 请求各自随机落在不同 worker 进程里。
  「接诊推送 → 叫号」「签发 → 回写」都是跨这三者的联动，进程内单例传不过去，
  必须走 Redis 发布/订阅做跨进程广播。

降级策略（与 redis_cache 熔断思路一致）：
  Redis 不可用时退化为「进程内直投」——本进程的订阅者仍能收到本进程发布的
  事件（开发环境单 worker 时完全等价）；跨进程投递则丢失，靠前端
  「断线重连后重拉今日队列」兜底，不丢病人。

频道约定：
  his:doctor:{doctor_id} : 推给某医生工作台的事件（接诊叫号 / 回写结果）
  his:wb:cmd             : 回写指令广播（持有 WS 连接的 worker 抢占执行）
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# 单个订阅队列的容量上限：SSE 消费方卡死时丢弃新事件（丢了靠重拉队列兜底），
# 绝不无限堆积拖垮进程内存
QUEUE_MAX = 100

# 泵死亡哨兵（2026-08-11 审计修复）：Redis pubsub 泵异常退出时投进订阅队列，
# 消费方（SSE gen / 回写 consumer_loop）收到即触发各自的重建/重连，避免永久失聪。
PUMP_DEAD_SENTINEL = "__bus_pump_dead__"

# 本地降级重试间隔（2026-08-13 第二轮审计修复）：Redis 不可用时订阅退化为
# 进程内直投，原实现就此**永不再试**——消费方阻塞在本地队列上，Redis 恢复后
# 这个 worker 永久收不到跨进程事件（回写指令、叫号），是个单向门。
# 现在降级订阅会定时投哨兵，让消费方退出重建订阅，从而周期性重试 Redis。
LOCAL_FALLBACK_RETRY_SECONDS = 30


def _put_pump_dead_sentinel(q: "asyncio.Queue") -> None:
    """保证哨兵必达：队列满时先腾一个位再投（泵已死，无并发写入竞争）。"""
    try:
        q.put_nowait({"type": PUMP_DEAD_SENTINEL})
    except asyncio.QueueFull:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            q.put_nowait({"type": PUMP_DEAD_SENTINEL})
        except asyncio.QueueFull:
            pass  # 极端并发下放弃，消费方 SSE 心跳/退避仍是最后兜底


class HisEventBus:
    """Redis 发布/订阅总线（Redis 不可用时退化为进程内直投）。"""

    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None
        # 订阅专用客户端：与 publish 用的分开，不设 socket_timeout（见 _get_sub_client）
        self._sub_client: Optional[aioredis.Redis] = None
        self._unavailable = False
        # 进程内直投注册表：channel → 本进程订阅队列集合（仅无 Redis 时使用）
        self._local: dict[str, set[asyncio.Queue]] = {}

    def _get_client(self) -> Optional[aioredis.Redis]:
        """lazy 建连；未配置 Redis 时返回 None 走进程内直投。"""
        if self._unavailable:
            return None
        if self._client is None:
            if not settings.redis_url:
                self._unavailable = True
                logger.warning("his_bus: Redis 未配置，事件总线退化为进程内直投")
                return None
            # decode_responses=True：本总线只传 JSON 文本，直接拿 str 省去手动解码
            # socket_timeout 必须有（2026-08-14 第八轮审计修复）：
            #
            # 原先只设了 socket_connect_timeout，也就是只管「连不上」，不管
            # 「连上了但不回话」。Redis 进程还活着却停止响应的场景在这台 2 核 4G
            # 机器上很现实——swap、maxmemory 触顶后的淘汰风暴、宿主网络单向不通，
            # TCP 都是已建立状态。那时 `await client.publish(...)` 没有任何超时，
            # 会无限期挂住。
            # 而 publish 就在 HIS WS 的**串行**消息循环里（his_ws 一条一条 await
            # 处理，这是有意设计）：一次挂起就让整个循环停摆——后续接诊推送收不到、
            # 我方下行回写的 ack 也读不到（ack 走同一条循环）→ 所有在途回写
            # 10s×3 后判失败并把连接摘掉，90s 后厂商连接被空闲超时关闭。
            # 同一进程里的 redis_cache 早就设了 socket_timeout=2.0 并带熔断，
            # 事件总线这两样都没有，降级哲学在这里断了档。
            self._client = aioredis.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
        return self._client

    def _get_sub_client(self) -> Optional[aioredis.Redis]:
        """订阅专用客户端：**不设 socket_timeout**（2026-08-14 修回归）。

        publish 侧必须有读超时，否则 Redis 假死时会顶死 HIS WS 的串行消息循环；
        但 pubsub 的 listen/get_message 本来就要长时间阻塞等消息——同一个 2 秒
        读超时套上去，订阅泵每 2 秒就抛一次 "Timeout reading from redis"、
        被判为泵终止，consumer 再每 5 秒重建订阅，整条 HIS 回写命令总线持续
        flapping（上线后生产日志实测到）。两种诉求相反，只能分成两个连接。

        断连检测改用 health_check_interval：redis-py 会定期发 PING 探活，
        既不会误杀正常的长阻塞，又能发现真正断掉的连接。
        """
        if self._unavailable or not settings.redis_url:
            return None
        if self._sub_client is None:
            self._sub_client = aioredis.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=2.0,
                # 不设 socket_timeout —— 订阅就是要长时间等
                health_check_interval=30,
            )
        return self._sub_client

    async def publish(self, channel: str, event: dict) -> None:
        """发布事件：优先 Redis 广播（覆盖所有 worker），失败落回进程内直投。

        进程内队列只在「订阅时 Redis 不可用」才存在，与 Redis 订阅互斥，
        两路都投也不会重复送达同一个订阅者。
        """
        text = json.dumps(event, ensure_ascii=False)
        client = self._get_client()
        if client is not None:
            try:
                await client.publish(channel, text)
            except Exception as exc:
                logger.warning("his_bus.publish: Redis 失败转本地直投 channel=%s err=%s",
                               channel, exc)
        self._deliver_local(channel, event)

    def _deliver_local(self, channel: str, event: dict) -> None:
        """进程内直投：满队列丢弃（订阅方断线重拉兜底），不阻塞发布方。"""
        for q in self._local.get(channel, set()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("his_bus.local: 队列满丢弃事件 channel=%s", channel)

    @asynccontextmanager
    async def _local_fallback(
        self, channel: str, q: asyncio.Queue, *, retry: bool
    ) -> AsyncIterator[asyncio.Queue]:
        """进程内直投降级订阅。

        retry=True 时起一个定时任务周期投哨兵——消费方收到即退出并重建订阅，
        于是 Redis 恢复后能重新走 pubsub（2026-08-13 修「降级即永久失聪」的单向门）。
        未配置 Redis 的本地开发同样走这里：哨兵只会让消费方每 30s 重建一次订阅，
        无副作用。
        """
        self._local.setdefault(channel, set()).add(q)
        ticker: asyncio.Task | None = None
        if retry:
            async def _tick() -> None:
                try:
                    await asyncio.sleep(LOCAL_FALLBACK_RETRY_SECONDS)
                    _put_pump_dead_sentinel(q)
                except asyncio.CancelledError:
                    raise
            ticker = asyncio.create_task(_tick())
        try:
            yield q
        finally:
            if ticker is not None:
                ticker.cancel()
            self._local.get(channel, set()).discard(q)

    @asynccontextmanager
    async def subscription(self, channel: str) -> AsyncIterator[asyncio.Queue]:
        """订阅频道，yield 一个 asyncio.Queue（元素为 dict 事件）。

        Redis 可用：pubsub 订阅 + 后台泵任务转投队列；
        Redis 不可用：注册进程内直投队列。
        上下文退出时自动清理（SSE 断开 / 任务取消都会走到）。
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        client = self._get_sub_client()
        if client is None:
            async with self._local_fallback(channel, q, retry=True) as fq:
                yield fq
            return

        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(channel)
        except Exception as exc:
            # 订阅失败（Redis 刚挂）：退化为进程内直投，并定时投哨兵促使重订阅
            logger.warning("his_bus.subscribe: Redis 失败转本地 channel=%s err=%s",
                           channel, exc)
            async with self._local_fallback(channel, q, retry=True) as fq:
                yield fq
            return

        pump = asyncio.create_task(self._pump(pubsub, q, channel))
        try:
            yield q
        finally:
            pump.cancel()
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass  # 清理失败不影响主流程（连接可能已断）

    @staticmethod
    async def _pump(pubsub, q: asyncio.Queue, channel: str) -> None:
        """后台泵：把 Redis pubsub 消息解析为 dict 投进订阅队列。"""
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue  # 跳过 subscribe 确认等控制消息
                try:
                    q.put_nowait(json.loads(msg["data"]))
                except asyncio.QueueFull:
                    logger.warning("his_bus.pump: 队列满丢弃事件 channel=%s", channel)
                except (ValueError, TypeError):
                    logger.warning("his_bus.pump: 非法 JSON 丢弃 channel=%s", channel)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 泵挂了（Redis 断连，redis-py 默认不自动重订阅）：不能只记日志——
            # 否则订阅方队列永远为空、SSE 端点仍每 25s 发心跳假活、回写消费循环永久
            # 失聪，且都不自愈（2026-08-11 审计修复）。这里向队列投哨兵，让消费方
            # 感知泵死并走各自的重建/重连逻辑（SSE 端结束流触发前端重连重拉，
            # 回写消费循环 raise 后走 5s 退避重建订阅）。
            logger.warning("his_bus.pump: 泵终止 channel=%s err=%s，投哨兵通知消费方", channel, exc)
            _put_pump_dead_sentinel(q)

    async def try_claim(self, key: str, ttl: int) -> bool:
        """跨 worker 抢占标记（SET NX EX）：谁抢到谁执行，防止重复回写。

        降级口径分两种（2026-08-13 第五轮审计修复）：
          · **未配置 Redis** → 返回 True。事件只在进程内流转，本就没有并发对手，
            放行是对的。
          · **Redis 报错** → 返回 False（fail-closed）。此时 Redis 是配置了的，
            意味着确实有别的 worker 在跑，而它可能已经抢到并正在执行——
            这边再返回 True 就是两个 worker 同时往医院 HIS 推同一份病历。
            本项目第二轮审计已确立原则：**有对外副作用的降级一律 fail-closed**
            （见 acquire_lock 的 fail_open 参数），回写是往院方系统推数据，
            属于最典型的对外副作用。
            代价是这一轮可能没人执行，但回写有对账循环兜底重投，漏一轮会被补上；
            而重复推送是当场就发生的、不可撤回的对外动作。
        """
        client = self._get_client()
        if client is None:
            return True
        try:
            return bool(await client.set(key, "1", nx=True, ex=ttl))
        except Exception as exc:
            logger.warning(
                "his_bus.claim: Redis 失败，保守判为未抢到（避免重复回写），"
                "本轮交由对账循环兜底 key=%s err=%s", key, exc,
            )
            return False

    async def is_claimed(self, key: str) -> bool:
        """查询抢占标记是否已存在（派发方判断是否需要本地兜底执行）。"""
        client = self._get_client()
        if client is None:
            return False
        try:
            return bool(await client.exists(key))
        except Exception:
            return False

    async def close(self) -> None:
        """关闭 Redis 连接（应用退出 / 测试清理用）。"""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None


# 全局单例：WS 路由（接诊事件）、签发钩子（回写指令）、SSE 端点（订阅）共用
his_event_bus = HisEventBus()
