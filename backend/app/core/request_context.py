"""
请求上下文（core/request_context.py）

职责：
  - 给每个 HTTP 请求生成 / 沿用一个 request_id（UUID 短串）
  - 用 contextvars 在异步任务间传递（asyncio 任务自动继承父 context）
  - 提供 logging.Filter 把 request_id 注入到 LogRecord，让 formatter 显示
  - Middleware 在 response 头回写 X-Request-ID，前端可拿到对应日志

定位价值：
  排查线上 bug 时，一个 API 请求会触发数十条日志（路由 + service + ORM）。
  没有 request_id 时只能按时间窗口反推，多用户并发场景里完全乱套。
  有了 request_id：grep "rid=abc12345" 一秒钉住一次完整调用链。

使用方式：
  - main.py 注册 RequestIDMiddleware
  - logging_config.py 给所有 handler 加 RequestIDFilter
  - formatter 加 %(request_id)s 字段
  - 业务代码不需要任何改动，contextvar 自动传播
"""

import logging
import time
import uuid
from contextvars import ContextVar
from typing import Optional  # noqa: F401  bind_user_context 签名需要

# 模块级 logger：请求访问日志走这里，方便单独控制级别
_access_logger = logging.getLogger("app.access")

# 不打访问日志的路径（高频探活/静态资源会刷屏）
_ACCESS_LOG_SKIP = ("/health", "/api/v1/health", "/docs", "/redoc", "/openapi.json", "/favicon.ico")

# 当前请求的 ID。中间件 set，handler 内任意位置 get（含异步嵌套调用）。
# 默认 "-" 表示"非请求上下文"，例如启动钩子 / 后台任务。
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
# 当前请求的认证用户 ID（user_uuid 短串）。
# 由 get_current_user dependency 验证完用户后调 bind_user_context() 写入。
# 鉴权前 / 公开端点 / 启动钩子 → "-"
_user_id: ContextVar[str] = ContextVar("user_id", default="-")


def get_request_id() -> str:
    """业务代码可以直接调用拿当前 request_id（极少用到，主要给 audit 等场景）。"""
    return _request_id.get()


def set_request_id(value: str) -> None:
    """少数场景下手动塞 request_id（如测试 / 后台任务），生产路径不需要调。"""
    _request_id.set(value)


def bind_user_context(user_id: Optional[str], username: Optional[str] = None) -> None:
    """认证 dependency 验证完用户后调本函数：

    1. 把 user_id 写入 contextvar，供 RequestIDFilter 注入到 LogRecord
    2. 同时调 sentry_sdk.set_user，让 Sentry event 自带用户信息
       （Sentry 控制台能按 user 维度筛选 issue，"哪个医生触发的 bug" 一目了然）

    注意：username 不写日志（仅给 Sentry user.username 字段），避免日志里出现真实姓名。
    """
    _user_id.set(user_id or "-")
    try:
        import sentry_sdk
        if user_id:
            # send_default_pii=False 已关 IP，这里只塞 id + username（非 PII）
            sentry_sdk.set_user({"id": user_id, "username": username or ""})
    except Exception:
        # sentry-sdk 未安装或未初始化都不影响主流程
        pass


def get_user_id() -> str:
    """业务代码读当前用户 ID（极少用，audit/log 增强场景）。"""
    return _user_id.get()


class RequestIDFilter(logging.Filter):
    """把 contextvar 里的 request_id / user_id 注入 LogRecord。

    所有 handler 都要挂这个 filter，否则 LogRecord 没有 request_id / user_id 属性
    会让 formatter 报 KeyError。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.user_id = _user_id.get()
        return True  # 永不过滤掉日志，仅注入字段


class RequestIDMiddleware:
    """每个 HTTP 请求生成 request_id 并注入 contextvar 与 response header。

    用 pure ASGI 风格而非 BaseHTTPMiddleware：
      Starlette 的 BaseHTTPMiddleware 把 endpoint 跑在独立 task 里，
      ContextVar 修改在 task 间不传播——dependency 里 set 的 user_id
      在 middleware finally 里读到的还是初始值。
      ASGI middleware 与 endpoint 在同一 task，ContextVar 完全互通。

    职责：
    - 优先读 `X-Request-ID` 请求头（前端透传 / 网关链路追踪场景）
    - 否则生成 8 字符短 UUID（足够单机不冲突，又不至于太长污染日志）
    - response 自动回写 `X-Request-ID`，前端报错时可截图给后端定位
    - Sentry 接入后，Sentry 也会自动把 contextvar 抓进 event tags
    - 请求结束打 request.access 日志（含耗时）
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope_type = scope["type"]
        # lifespan 不需要 request_id（应用启动/关闭事件，与单次请求无关）
        if scope_type == "lifespan":
            await self.app(scope, receive, send)
            return

        # http 与 websocket 都注入 rid——WS 是长连接，整个连接共用一个 rid
        # 否则 voice_stream 的日志没法 grep 到完整链路
        if scope_type not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # 提取 X-Request-ID 头（headers 是 [(name_bytes, value_bytes)] 列表）
        incoming = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-request-id":
                incoming = value.decode("latin-1", errors="replace")
                break
        rid = incoming if incoming and len(incoming) <= 64 else uuid.uuid4().hex[:8]

        rid_token = _request_id.set(rid)
        # 重置 user_id：每个请求开始时为 "-"，鉴权 dependency 后才填
        # 必须重置——否则跨请求残留会出现 A 用户日志带 B 用户 uid 的事故
        uid_token = _user_id.set("-")
        start = time.perf_counter()
        # 用 list 装 status，闭包可修改（send_wrapper 设值，finally 读）
        captured = {"status": 500}

        try:
            # 给 Sentry 打 tag
            try:
                import sentry_sdk
                sentry_sdk.set_tag("request_id", rid)
                sentry_sdk.set_user(None)  # 鉴权 dependency 里 bind 真用户
            except Exception:
                pass

            # 包装 send：在 response.start 时注入 X-Request-ID 头 + 抓 status
            # WebSocket 不走 response.start，accept 也不带 header，所以 wrapper
            # 对 ws 是无操作（仅 http 走得到注入分支），但保持同一份 wrapper 逻辑简洁
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    captured["status"] = message["status"]
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", rid.encode("latin-1")))
                    message["headers"] = headers
                await send(message)

            await self.app(scope, receive, send_wrapper)
        finally:
            # 算耗时 + 打访问日志
            # WebSocket 不打 access 行（连接级日志已经由 voice_stream.start/end 覆盖）
            # HTTP 跳过 health/docs 等高频路径避免刷屏
            duration_ms = int((time.perf_counter() - start) * 1000)
            path = scope.get("path", "")
            if scope_type == "http" and not any(path.startswith(p) for p in _ACCESS_LOG_SKIP):
                # 慢请求（>1s）升级到 warning，方便 grep
                level = logging.WARNING if duration_ms > 1000 else logging.INFO
                _access_logger.log(
                    level,
                    "request.access: method=%s path=%s status=%d duration_ms=%d",
                    scope.get("method", "?"), path, captured["status"], duration_ms,
                )
            # 必须 reset，否则 contextvar 会污染同 worker 后续请求
            _request_id.reset(rid_token)
            _user_id.reset(uid_token)
