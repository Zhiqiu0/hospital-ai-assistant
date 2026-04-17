"""
统一日志配置（core/logging_config.py）

配置三个输出目标：
  1. 控制台（stderr）    : DEBUG+ 级，开发调试用
  2. logs/app.log        : INFO+ 级，按天轮转，保留 30 天，记录完整运行日志
  3. logs/error.log      : WARNING+ 级，按天轮转，保留 30 天，只含告警和错误

日志格式：
  "2024-01-01 12:00:00 [INFO] app.api.v1.auth: 用户登录成功"

热重载兼容：
  检查 root.handlers 是否为空，避免 uvicorn --reload 时重复添加 handler。

第三方库噪音抑制：
  uvicorn.access、sqlalchemy.engine、httpx 的 INFO 级日志量很大，
  统一调到 WARNING 以上，保持日志可读性。

使用方式：
  from app.core.logging_config import setup_logging
  setup_logging(log_level="INFO")  # 在 main.py 启动时调用一次
"""

import logging
import logging.handlers
from pathlib import Path

# 日志目录：backend/logs/（相对于本文件向上三级）
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"


def setup_logging(log_level: str = "INFO") -> None:
    """初始化全局日志配置。

    Args:
        log_level: 根 logger 的最低级别，如 "DEBUG"/"INFO"/"WARNING"。
                   来自 settings.log_level，默认 "INFO"。
    """
    # 确保日志目录存在（首次部署时自动创建）
    LOGS_DIR.mkdir(exist_ok=True)

    # 统一日志格式：时间 + 级别 + 模块路径 + 消息
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    # ── 控制台 handler ─────────────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)  # 控制台输出所有级别，方便开发调试
    console.setFormatter(formatter)

    # ── app.log handler（完整运行日志）────────────────────────────────────────
    # when="midnight": 每天 0 点切换到新文件，旧文件追加日期后缀
    # backupCount=30 : 保留最近 30 个日志文件，共约 1 个月
    app_file = logging.handlers.TimedRotatingFileHandler(
        filename=LOGS_DIR / "app.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    app_file.setLevel(logging.INFO)
    app_file.setFormatter(formatter)

    # ── error.log handler（仅告警和错误）──────────────────────────────────────
    # 排查线上问题时只看 error.log，信噪比高
    err_file = logging.handlers.TimedRotatingFileHandler(
        filename=LOGS_DIR / "error.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    err_file.setLevel(logging.WARNING)
    err_file.setFormatter(formatter)

    # ── 根 logger 配置 ─────────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 热重载兼容：仅在 handlers 为空时添加，避免 uvicorn --reload 重复挂载
    if not root.handlers:
        root.addHandler(console)
        root.addHandler(app_file)
        root.addHandler(err_file)

    # ── 第三方库噪音抑制 ────────────────────────────────────────────────────────
    # uvicorn.access: 每个 HTTP 请求都会打一行日志，量大且无业务价值
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # sqlalchemy.engine: echo=True 时会输出所有 SQL，已有 DB 级 debug 机制
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # httpx: LLM 客户端每次请求都输出 DEBUG 日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
