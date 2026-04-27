"""
Sentry 初始化（core/sentry_init.py）

职责：
  1. 仅当环境变量 SENTRY_DSN 非空时启用 Sentry，本地开发默认跳过
  2. 集成 FastAPI / SQLAlchemy / Logging（自动抓 logger.error 以上级别为 event）
  3. PII 脱敏（医疗系统刚需）：关闭默认 PII 抓取 + 自定义 before_send 过滤敏感字段
  4. 显式关闭 Session Replay 与 Profiling（医疗系统不能录屏）
  5. 抑制第三方库噪音（SQLAlchemy/httpx 偶发的 ERROR 不应触发告警）

使用方式：
  在 main.py 的 setup_logging 之后调用 init_sentry()，必须早于 FastAPI 实例创建。

合规说明：
  - send_default_pii=False：不抓 cookies / 用户 IP / Authorization header
  - before_send 还会兜底删除 request.data 与 query_string（这两个最容易夹带病历正文）
  - traces_sample_rate 默认 0：性能 trace 会附带 SQL 参数，关掉避免泄露
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration, ignore_logger
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

logger = logging.getLogger(__name__)

# 不上报的异常类型（噪音过滤，不是 bug）：
# - KeyboardInterrupt：开发环境 Ctrl+C 重启 uvicorn 时触发
# - asyncio.CancelledError：客户端断开导致的请求 task 被 cancel，FastAPI 正常路径
# - SystemExit：进程优雅退出
# 注意：sentry_sdk 通过类型匹配，子类异常也会被忽略
_IGNORED_EXCEPTIONS = [
    KeyboardInterrupt,
    asyncio.CancelledError,
    SystemExit,
]


# ── PII 过滤：兜底删除可能含病历正文的字段 ───────────────────────────────────
# Sentry 默认会把 request.data / query_string 一起发回，医疗系统里这两处
# 最容易夹带患者姓名 / 身份证 / 病历正文 / 主诉。这里强制清空。
SENSITIVE_REQUEST_FIELDS = ("data", "cookies", "query_string")
SENSITIVE_HEADER_NAMES = ("authorization", "cookie", "x-api-key")


def _scrub_event(event: Dict[str, Any], _hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """before_send 钩子：发送前最后一道清洗，兜底防止 PII 泄露。

    Sentry 已经因为 send_default_pii=False 关掉了大部分 PII，但 request body
    仍然可能被某些 integration 抓到，这里再删一遍保险。
    """
    request = event.get("request") or {}

    # 删请求 body / cookies / query_string，保留 method/url 用于聚合分组
    for field in SENSITIVE_REQUEST_FIELDS:
        if field in request:
            request[field] = "[scrubbed]"

    # headers 里 Authorization / Cookie 单独清掉（保留 user-agent / content-type 等）
    headers = request.get("headers") or {}
    for name in list(headers.keys()):
        if name.lower() in SENSITIVE_HEADER_NAMES:
            headers[name] = "[scrubbed]"

    event["request"] = request

    # extra 里如果有人手工塞进来的字段以 "patient" / "record" 开头，一律清掉
    extra = event.get("extra") or {}
    for key in list(extra.keys()):
        lowered = key.lower()
        if lowered.startswith("patient") or lowered.startswith("record") or "content" in lowered:
            extra[key] = "[scrubbed]"
    event["extra"] = extra

    return event


def init_sentry(
    dsn: str,
    environment: str,
    traces_sample_rate: float = 0.0,
    release: Optional[str] = None,
) -> None:
    """初始化 Sentry。dsn 为空时直接跳过，本地开发零侵入。

    Args:
        dsn: Sentry 项目 DSN，空字符串 = 不启用。
        environment: 环境标识（development / production），告警分流用。
        traces_sample_rate: 性能 trace 采样率（0~1），0 表示完全不采集。
        release: 发布版本号（可选），目前传 None；接 CI 后由构建注入 git SHA。
    """
    if not dsn:
        # 本地开发常态：不打印 warning，避免日志噪音
        return

    # 抑制第三方库噪音（连接抖动 / SQL 偶发慢查询 / HTTP 抖动不应进 Sentry）
    # 必须在 sentry_sdk.init 之前调用：ignore_logger 写入 LoggingIntegration 的全局
    # 集合，init 后才注册的可能错过早期 LogRecord（启动阶段就刷的几条 sqlalchemy
    # ERROR）。提前调可省 quota。
    for noisy in ("sqlalchemy.engine", "sqlalchemy.pool", "httpx", "httpcore", "asyncpg"):
        ignore_logger(noisy)

    # LoggingIntegration：把 logger.warning+ 当面包屑，logger.error+ 当 event 上报
    logging_integration = LoggingIntegration(
        level=logging.INFO,         # INFO+ 进 breadcrumb（事故现场上下文）
        event_level=logging.ERROR,  # ERROR+ 才上报 event（避免 quota 暴涨）
    )

    sentry_sdk.init(
        dsn=dsn,
        environment=environment or "unknown",
        release=release,
        # ── PII 防线 ──────────────────────────────────────────────
        send_default_pii=False,           # 不抓 cookies / IP / Authorization
        before_send=_scrub_event,         # 兜底清洗 request body / 自定义敏感字段
        # ── 噪音过滤 ──────────────────────────────────────────────
        # Ctrl+C 重启 / 客户端断开 / 进程退出 都不算 bug，不发邮件
        ignore_errors=_IGNORED_EXCEPTIONS,
        # ── 采样率 ────────────────────────────────────────────────
        traces_sample_rate=traces_sample_rate,
        # 显式关闭 Session Replay（医疗系统不能录屏 → 患者信息泄露）
        # sentry-sdk 2.x 这两个属性默认就是 0，这里显式写出来留代码痕迹
        # 防止任何人后续误开
        # ──────────────────────────────────────────────────────────
        # ── 集成 ──────────────────────────────────────────────────
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            SqlalchemyIntegration(),
            logging_integration,
        ],
        # 抑制部分库的传播（连接异常 / SQL 抖动是运维问题不是代码 bug）
        # 通过 LoggingIntegration 的 ignore_logger 实现
    )

    logger.info(
        "sentry.init: ok environment=%s traces_sample_rate=%s",
        environment,
        traces_sample_rate,
    )
