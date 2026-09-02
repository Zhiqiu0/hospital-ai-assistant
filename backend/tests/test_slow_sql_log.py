# -*- coding: utf-8 -*-
"""慢 SQL 日志（2026-09-02 可观测性专项）。

排障链路此前断在这里：访问日志能回答"哪个接口慢"（request.access 的
duration_ms），但"为什么慢、是哪条 SQL"查不到——DB_ECHO 是全开全关的开关，
每条 SQL 往 stdout 写会阻塞 asyncio event loop（PACS 端点曾因此 5s+），生产
不能开；PG 侧 log_min_duration_statement 实测也是 -1（关闭），且那边的日志既
不在 /app/logs、也没有 rid 能和请求关联。

本文件锁两件事：钩子真的会在超阈值时记录；**日志里绝不出现参数值**——那里是
患者姓名、身份证、病历正文。

注：钩子挂在 app.database.engine 上，而 conftest 的 async_db 用的是它自己建的
engine，必须对真实 engine 发查询才测得到（第一版正是这么写错的）。
"""
import logging

import pytest
from sqlalchemy import text


class _Cap(logging.Handler):
    def __init__(self):
        super().__init__()
        self.msgs: list[str] = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


@pytest.fixture
def capture(monkeypatch):
    """挂日志捕获 + 把阈值调成参数化的值。"""
    def _make(threshold_ms: float) -> _Cap:
        import app.database as db

        cap = _Cap()
        lg = logging.getLogger("app.db")
        lg.addHandler(cap)
        lg.setLevel(logging.WARNING)
        monkeypatch.setattr(db, "_SLOW_SQL_MS", threshold_ms)
        _handlers.append((lg, cap))
        return cap

    _handlers: list = []
    yield _make
    for lg, cap in _handlers:
        lg.removeHandler(cap)


async def _run(sql: str, params: dict | None = None) -> None:
    from app.database import engine

    async with engine.connect() as conn:
        await conn.execute(text(sql), params or {})


@pytest.mark.asyncio
async def test_超阈值的查询会被记录(capture):
    cap = capture(0.0)          # 阈值归零：每条都记
    await _run("SELECT 1")
    assert any("db.slow_query" in m for m in cap.msgs), "钩子没触发"


@pytest.mark.asyncio
async def test_只记SQL模板不记参数值(capture):
    """参数里是 PHI。SQLAlchemy 的 statement 是带占位符的模板，既安全又可聚合
    ——同一条慢查询在日志里是同一个字符串，能直接统计出现次数。"""
    cap = capture(0.0)
    await _run("SELECT :secret AS s", {"secret": "患者张三 330523199001019878"})
    joined = "\n".join(cap.msgs)
    assert "张三" not in joined, "患者姓名进了慢 SQL 日志"
    assert "330523199001019878" not in joined, "身份证进了慢 SQL 日志"
    assert "SELECT" in joined.upper(), "SQL 模板本身没记下来，日志失去意义"


@pytest.mark.asyncio
async def test_未超阈值的查询不记(capture):
    """默认 500ms 阈值下普通查询不该刷屏——噪音会把真慢查询淹掉，
    而这个模块存在的意义正是让慢查询显眼。"""
    cap = capture(500.0)
    await _run("SELECT 1")
    assert not [m for m in cap.msgs if "db.slow_query" in m]
