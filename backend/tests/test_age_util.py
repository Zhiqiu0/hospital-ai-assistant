"""utils.calc_age 单元测试

覆盖三种边界：
  - 出生日期为 None → 返回 None
  - 当年还没过生日 → 减 1
  - 当年生日已过/正好今天 → 不减
"""
from datetime import date

from app.utils.age import calc_age


def test_calc_age_none_returns_none():
    assert calc_age(None) is None


def test_calc_age_birthday_today_no_subtract():
    # 2026-04-25 出生日是 2000-04-25 → 今天就是 26 岁生日
    assert calc_age(date(2000, 4, 25), date(2026, 4, 25)) == 26


def test_calc_age_birthday_not_passed_subtract_one():
    # 生日还没到（明天才到）→ 周岁还是 25
    assert calc_age(date(2000, 4, 26), date(2026, 4, 25)) == 25


def test_calc_age_birthday_passed_full_year():
    # 生日已过（昨天）→ 26 岁
    assert calc_age(date(2000, 4, 24), date(2026, 4, 25)) == 26


def test_calc_age_february_29_leap_year_edge():
    # 闰年 2 月 29 日出生，今年没有 2/29 → 视作 3/1 之后才算过生日
    # 2026-02-28 时还差一天 → 25 岁
    assert calc_age(date(2000, 2, 29), date(2026, 2, 28)) == 25
    # 2026-03-01 时已过 → 26 岁
    assert calc_age(date(2000, 2, 29), date(2026, 3, 1)) == 26
