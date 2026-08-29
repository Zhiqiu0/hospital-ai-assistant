"""
统一日志配置（core/logging_config.py）

配置三个输出目标：
  1. 控制台（stderr）    : DEBUG+ 级，开发调试用
  2. logs/app.log        : INFO+ 级，按天轮转，保留 30 天，记录完整运行日志
  3. logs/error.log      : WARNING+ 级，按天轮转，保留 30 天，只含告警和错误

日志格式：
  "2024-01-01 12:00:00 [INFO] [rid=abc12345] app.api.v1.auth: 用户登录成功"
  rid 段是 RequestIDMiddleware 注入的请求 ID，非 HTTP 上下文时显示 "-"

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

# RequestIDFilter 把 contextvar 里的 request_id 注入到每条日志记录
# formatter 用 %(request_id)s 才能渲染出 [rid=xxx] 段
from app.core.request_context import RequestIDFilter

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

    # 统一日志格式：时间 + 级别 + request_id + user_id + 模块路径 + 消息
    # [rid=xxx] 单请求全链路 grep；[uid=xxx] 用户维度筛选；均为 "-" 表示无上下文
    fmt = "%(asctime)s [%(levelname)s] [rid=%(request_id)s uid=%(user_id)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    # 所有 handler 都要挂 RequestIDFilter，否则 LogRecord 缺 request_id 字段
    # 会让 formatter 报 KeyError
    rid_filter = RequestIDFilter()

    # ── 控制台 handler ─────────────────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)  # 控制台输出所有级别，方便开发调试
    console.setFormatter(formatter)
    console.addFilter(rid_filter)

    # ── app.log handler（完整运行日志）────────────────────────────────────────
    # 为什么用 WatchedFileHandler 而不是 TimedRotatingFileHandler
    # （2026-08-13 第二轮审计修复）：生产是 uvicorn --workers 2，两个进程各持
    # 一个 handler 写同一个文件。TimedRotatingFileHandler 到午夜会各自尝试
    # rename，竞态下轻则丢日志，重则某个 worker 之后一直往已被改名的旧 inode 写
    # ——那半边日志从 error.log 里彻底消失，而本项目排障的第一条铁律就是
    # "先看 error.log"，等于排障入口静默瘸掉一半。
    # WatchedFileHandler 专为「外部工具轮转」设计：检测到文件被换掉就重新打开，
    # 多进程安全；轮转交给 deploy 配的每日 cron（rotate_logs.sh）单进程执行。
    # 文件 handler 构造包容错（2026-08-29 第九轮回归修复）：WatchedFileHandler
    # 构造即打开/创建文件，日志目录权限异常（cap_drop 后权限位不再豁免、
    # 挂载错目录等）会直接抛 PermissionError 把整个后端打死——日志是排障
    # 工具，绝不能反过来成为服务的死因。建不出来就降级只写 stdout
    # （docker 日志仍在），并打一条显眼告警。
    def _try_file_handler(filename, level):
        try:
            h = logging.handlers.WatchedFileHandler(filename=filename, encoding="utf-8")
        except OSError as exc:
            print(f"[logging] 文件日志不可用（{exc}），降级仅 stdout：{filename}",
                  flush=True)
            return None
        h.setLevel(level)
        h.setFormatter(formatter)
        h.addFilter(rid_filter)
        return h

    app_file = _try_file_handler(LOGS_DIR / "app.log", logging.INFO)

    # ── error.log handler（仅告警和错误）──────────────────────────────────────
    # 排查线上问题时只看 error.log，信噪比高
    err_file = _try_file_handler(LOGS_DIR / "error.log", logging.WARNING)

    # ── 根 logger 配置 ─────────────────────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 热重载兼容：仅在 handlers 为空时添加，避免 uvicorn --reload 重复挂载
    if not root.handlers:
        root.addHandler(console)
        if app_file is not None:
            root.addHandler(app_file)
        if err_file is not None:
            root.addHandler(err_file)

    # ── 第三方库噪音抑制 ────────────────────────────────────────────────────────
    # uvicorn.access: 每个 HTTP 请求都会打一行日志，量大且无业务价值
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # sqlalchemy.engine: echo=True 时会输出所有 SQL，已有 DB 级 debug 机制
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # httpx: LLM 客户端每次请求都输出 DEBUG 日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
