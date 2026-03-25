"""
统一日志配置
- 控制台：INFO 级，带时间戳和模块名
- 文件：logs/app.log，按天轮转，保留 30 天
- 错误：logs/error.log，只写 WARNING 及以上
"""
import logging
import logging.handlers
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent.parent / "logs"


def setup_logging(log_level: str = "INFO") -> None:
    LOGS_DIR.mkdir(exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt, datefmt=datefmt)

    # ── 控制台 ──────────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    console.setFormatter(formatter)

    # ── app.log（按天轮转，保 30 天）───────────────────────
    app_file = logging.handlers.TimedRotatingFileHandler(
        filename=LOGS_DIR / "app.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    app_file.setLevel(logging.INFO)
    app_file.setFormatter(formatter)

    # ── error.log（只写 WARNING+）──────────────────────────
    err_file = logging.handlers.TimedRotatingFileHandler(
        filename=LOGS_DIR / "error.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    err_file.setLevel(logging.WARNING)
    err_file.setFormatter(formatter)

    # ── 根 logger ──────────────────────────────────────────
    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    # 避免重复添加 handler（热重载场景）
    if not root.handlers:
        root.addHandler(console)
        root.addHandler(app_file)
        root.addHandler(err_file)

    # 静默第三方噪音
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
