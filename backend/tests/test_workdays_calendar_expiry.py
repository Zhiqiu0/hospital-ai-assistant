# -*- coding: utf-8 -*-
"""节假日日历过期必须有信号（2026-08-31 跨年边界审计回归锁）。

`services/workdays.py` 的 HOLIDAYS/EXTRA_WORKDAYS 是手工维护到某一年为止的
（国办通常在上一年 11 月才发布次年安排，无法预置）。超出覆盖年份后 is_workday
会**静默退化**成"只看周末"——2027 年的元旦、春节、国庆全被当成工作日。

危害不是崩溃，是**假指标**：
  · 病区列表的「出院后保留 7 个工作日」窗口提前关闭，已出院但文书没写完的接诊
    会从医生的病区视图消失，而那是住院端唯一的接诊入口；
  · 「7 个工作日内归档」的达标率被算低，进医务科对外通报的《病案首页质量通报》。

add_workdays 早有告警，但 inpatient_service 是逐日回退直接调 is_workday，绕过了
那条路径。这里把三层信号钉住：is_workday 自身告警、calendar_status 提前预警、
深度健康检查暴露。
"""
from datetime import date

import pytest

from app.services import workdays
from app.services.workdays import _CALENDAR_YEAR, calendar_status, is_workday


def test_覆盖年内是ok():
    st, days = calendar_status(date(_CALENDAR_YEAR, 3, 1))
    assert st == "ok"
    assert days > 60


def test_临近年末提前预警():
    """留 60 天余量：国办 11 月发布次年安排，运维有充足时间更新。"""
    st, days = calendar_status(date(_CALENDAR_YEAR, 11, 5))
    assert st == "expiring"
    assert 0 < days <= 60


def test_跨出覆盖年份判expired():
    st, _ = calendar_status(date(_CALENDAR_YEAR + 1, 1, 5))
    assert st == "expired"


def test_is_workday对未覆盖年份告警(caplog, monkeypatch):
    """这是本次补的核心：此前只有 add_workdays 会喊，直接调 is_workday 零信号。"""
    monkeypatch.setattr(workdays, "_WARNED_YEARS", set())
    with caplog.at_level("WARNING"):
        is_workday(date(_CALENDAR_YEAR + 1, 1, 1))
    assert any("法定节假日未录入" in r.message for r in caplog.records), \
        "跨出日历覆盖年份时 is_workday 没有任何告警"


def test_同一年只告警一次(caplog, monkeypatch):
    """病区保留期是逐日回退循环调用的，每天喊一次会把 error.log 刷爆。"""
    monkeypatch.setattr(workdays, "_WARNED_YEARS", set())
    with caplog.at_level("WARNING"):
        for day in range(1, 15):
            is_workday(date(_CALENDAR_YEAR + 1, 1, day))
    warns = [r for r in caplog.records if "法定节假日未录入" in r.message]
    assert len(warns) == 1, f"同一年告警了 {len(warns)} 次"


def test_覆盖年内不告警(caplog, monkeypatch):
    monkeypatch.setattr(workdays, "_WARNED_YEARS", set())
    with caplog.at_level("WARNING"):
        is_workday(date(_CALENDAR_YEAR, 6, 1))
    assert not [r for r in caplog.records if "法定节假日未录入" in r.message]


@pytest.mark.asyncio
async def test_深度健康检查暴露日历状态():
    """与 ai_credential 同一类：系统跑得好好的，但输出是错的——必须让
    uptime-kuma 看得见。"""
    from app.main import health_check_deep

    res = await health_check_deep()
    import json
    body = json.loads(res.body)
    assert "holiday_calendar" in body["deps"]
