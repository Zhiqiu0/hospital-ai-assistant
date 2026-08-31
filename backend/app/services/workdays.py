# -*- coding: utf-8 -*-
"""工作日日历（services/workdays.py，2026-08-21 阶段5）。

病案首页质控方案的"7 个工作日内完成归档"需要工作日语义（周末+法定节假日
不计）。此前系统只有自然时长（timedelta），无法表达工作日——用自然日近似
会把跨周末/长假的病历误判超时（假指标比没指标更糟）。

口径：
  - 周六/周日为休息日；
  - HOLIDAYS 为法定节假日（国务院办公厅年度安排）；
  - EXTRA_WORKDAYS 为调休上班的周末（同一来源）；
  - 年度更新：每年国办发布次年安排后在此追加（改动=改日历事实，走 PR review）。

2026 年安排依据：国务院办公厅关于 2026 年部分节假日安排的通知。
"""
import logging
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

# 日历覆盖到的年份——每年更新 HOLIDAYS/EXTRA_WORKDAYS 时同步 +1
_CALENDAR_YEAR = 2026

# 2026 法定节假日（放假日；含元旦/春节/清明/五一/端午/中秋/国庆）
HOLIDAYS: frozenset[date] = frozenset({
    # 元旦
    date(2026, 1, 1), date(2026, 1, 2),
    # 春节（2026-02-17 除夕前后）
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 2, 19), date(2026, 2, 20), date(2026, 2, 21), date(2026, 2, 22),
    # 清明
    date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
    # 劳动节
    date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
    date(2026, 5, 4), date(2026, 5, 5),
    # 端午
    date(2026, 6, 19), date(2026, 6, 20), date(2026, 6, 21),
    # 中秋
    date(2026, 9, 25), date(2026, 9, 26), date(2026, 9, 27),
    # 国庆
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3), date(2026, 10, 4),
    date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
})

# 调休上班的周末
EXTRA_WORKDAYS: frozenset[date] = frozenset({
    date(2026, 2, 14), date(2026, 2, 28),   # 春节调休
    date(2026, 4, 26), date(2026, 5, 9),    # 五一调休
    date(2026, 9, 20), date(2026, 10, 10),  # 中秋/国庆调休
})


# 已经告警过的年份——同一年只喊一次，避免逐日循环调用把 error.log 刷爆
_WARNED_YEARS: set[int] = set()


def is_workday(d: date) -> bool:
    """是否工作日：调休上班的周末算、法定节假日不算、普通周末不算。

    日历覆盖告警（2026-08-31 跨年边界审计补）：本表只维护到 _CALENDAR_YEAR 年，
    超出覆盖的年份会**静默退化**成"只看周末"——2027 年的元旦、春节、国庆全被
    当成工作日。add_workdays 早就有这层告警，但 inpatient_service 的病区保留期
    是「逐日回退直接调 is_workday」，绕过了那条路径，2027 年起会零信号地持续
    算错：已出院但文书没写完的接诊，会比真实 7 个工作日更早从医生的病区视图
    消失——而病区列表是住院端唯一的接诊入口。
    """
    if d.year > _CALENDAR_YEAR and d.year not in _WARNED_YEARS:
        _WARNED_YEARS.add(d.year)
        logger.warning(
            "workdays.calendar: %d 年的法定节假日未录入（日历只到 %d 年），"
            "该年份的节假日会被当成工作日 → 时限判定与质控指标失真。"
            "请更新 services/workdays.py 的 HOLIDAYS/EXTRA_WORKDAYS",
            d.year, _CALENDAR_YEAR,
        )
    if d in EXTRA_WORKDAYS:
        return True
    if d in HOLIDAYS:
        return False
    return d.weekday() < 5


def calendar_status(today: date | None = None) -> tuple[str, int]:
    """节假日日历的覆盖状态，供深度健康检查提前预警。

    国办通常在上一年 11 月才发布次年的节假日安排，所以这里不预置未来年份，
    改为「快到期就提醒运维去查国办通知」。

    Returns:
        (状态, 距覆盖年末的天数)；状态取值：
          ok       — 还早
          expiring — 覆盖年末已在 60 天内，该去查国办通知了
          expired  — 已经跨出覆盖年份，此刻所有工作日计算都在失真
    """
    d = today or date.today()
    if d.year > _CALENDAR_YEAR:
        return "expired", 0
    days_left = (date(_CALENDAR_YEAR, 12, 31) - d).days
    return ("expiring" if days_left <= 60 else "ok"), days_left


def add_workdays(start: datetime, n: int) -> datetime:
    """start 之后第 n 个工作日的同一时刻（n>=1）。

    "7 个工作日内完成" 的截止时刻 = add_workdays(start, 7)。
    """
    d = start.date()
    remaining = n
    while remaining > 0:
        d = d + timedelta(days=1)
        if is_workday(d):
            remaining -= 1
    # 日历覆盖告警（2026-08-28 体检）：本表只维护到 _CALENDAR_YEAR 年，
    # 跨年后新一年的法定假日未录入会被当工作日 → 截止时刻算早、把按时签发
    # 误判超时（假指标）。忘更新时至少让 error.log 里有迹可循。
    if d.year > _CALENDAR_YEAR:
        logger.warning(
            "workdays.calendar: 截止日 %s 超出节假日日历覆盖年份(%d)，"
            "请更新 services/workdays.py 的 HOLIDAYS/EXTRA_WORKDAYS",
            d.isoformat(), _CALENDAR_YEAR,
        )
    return datetime.combine(d, start.time())
