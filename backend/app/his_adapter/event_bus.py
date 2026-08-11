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


class HisEventBus:
    """Redis 发布/订阅总线（Redis 不可用时退化为进程内直投）。"""

    def __init__(self) -> None:
        self._client: Optional[aioredis.Redis] = None
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
            self._client = aioredis.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=2.0,
            )
        return self._client

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
    async def subscription(self, channel: str) -> AsyncIterator[asyncio.Queue]:
        """订阅频道，yield 一个 asyncio.Queue（元素为 dict 事件）。

        Redis 可用：pubsub 订阅 + 后台泵任务转投队列；
        Redis 不可用：注册进程内直投队列。
        上下文退出时自动清理（SSE 断开 / 任务取消都会走到）。
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        client = self._get_client()
        if client is None:
            self._local.setdefault(channel, set()).add(q)
            try:
                yield q
            finally:
                self._local.get(channel, set()).discard(q)
            return

        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(channel)
        except Exception as exc:
            # 订阅失败（Redis 刚挂）：退化为进程内直投，行为与未配置一致
            logger.warning("his_bus.subscribe: Redis 失败转本地 channel=%s err=%s",
                           channel, exc)
            self._local.setdefault(channel, set()).add(q)
            try:
                yield q
            finally:
                self._local.get(channel, set()).discard(q)
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
            # 泵挂了（Redis 断连）：订阅方队列不再有新事件，靠 SSE 心跳超时
            # 让前端重连重拉，这里只记日志
            logger.warning("his_bus.pump: 泵终止 channel=%s err=%s", channel, exc)

    async def try_claim(self, key: str, ttl: int) -> bool:
        """跨 worker 抢占标记（SET NX EX）：谁抢到谁执行，防止重复回写。

        Redis 不可用时返回 True——此时事件只在进程内流转，天然无并发抢占。
        """
        client = self._get_client()
        if client is None:
            return True
        try:
            return bool(await client.set(key, "1", nx=True, ex=ttl))
        except Exception as exc:
            logger.warning("his_bus.claim: Redis 失败按抢到处理 key=%s err=%s", key, exc)
            return True

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
