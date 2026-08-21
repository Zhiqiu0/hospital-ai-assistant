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
from datetime import date, datetime, timedelta

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


def is_workday(d: date) -> bool:
    """是否工作日：调休上班的周末算、法定节假日不算、普通周末不算。"""
    if d in EXTRA_WORKDAYS:
        return True
    if d in HOLIDAYS:
        return False
    return d.weekday() < 5


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
    return datetime.combine(d, start.time())
