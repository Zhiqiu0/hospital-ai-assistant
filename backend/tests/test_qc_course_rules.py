# -*- coding: utf-8 -*-
"""日常病程 / 上级查房质控规则测试（2026-09-16 实装）。

三条零误报规则的判据边界（每条对着 PDF 罚则原文，详见
_inpatient_checkers_course 头注）：
  IP-COURSE-01 内容空洞（<12 个汉字，日期/数字/标点不计）扣 2 分
  IP-COURSE-02 病程间隔超 3 天（+12h 宽限；最宽档零误报）扣 2 分
  IP-SENIOR-01 查房记录太简单（同字数判据）扣 1 分

重点测"从宽边界不误伤"：认真写的最简病程、临界间隔、未预取时间线，
一律不扣——引擎零误报纪录不能破功。
"""
from datetime import datetime, timedelta

from app.services.ai._qc_rubric import _select_rubric
from app.services.qc_engine.checker import CourseTimeline, build_context
from app.services.qc_engine.scorer import score

_RUBRIC = _select_rubric("course_record")


def _codes(report):
    return {d.rule_code for d in report.deductions}


def _score_course(text, timeline=None):
    ctx = build_context(text, record_type="course_record", course_timeline=timeline)
    return score(_RUBRIC, ctx)


# ── IP-COURSE-01 内容空洞 ────────────────────────────────────────────

def test_一句空话病程被扣():
    r = _score_course("患者今日无特殊。")  # 7 个汉字
    assert "IP-COURSE-01" in _codes(r)
    assert r.score == 98.0  # 18 分大项扣 2


def test_日期行不能给空话病程凑字数():
    # 日期/时间/数字/标点不计入有效字数——靠日期开头混不过阈值
    r = _score_course("2026-09-16 09:00 患者今日无特殊。")
    assert "IP-COURSE-01" in _codes(r)


def test_认真写的最简病程不误伤():
    r = _score_course("患者夜间安静入睡，无特殊主诉，生命体征平稳。")  # 18 字
    assert "IP-COURSE-01" not in _codes(r)


# ── IP-COURSE-02 间隔超时 ────────────────────────────────────────────

def _tl(*day_offsets):
    base = datetime(2026, 9, 1, 9, 0)
    return CourseTimeline(
        recorded_ats=tuple(base + timedelta(days=d) for d in day_offsets),
        loaded=True,
    )

_OK_TEXT = "患者病情平稳，双肺呼吸音清，继续原治疗方案，密切观察病情变化。"


def test_间隔超3天被扣():
    r = _score_course(_OK_TEXT, timeline=_tl(0, 5))  # 相隔 5 天
    assert "IP-COURSE-02" in _codes(r)


def test_间隔正好3天不扣():
    # 每 3 天 1 次是合规底线本身；再加 12h 钟点宽限（第 3 天下午补记不算违规）
    r = _score_course(_OK_TEXT, timeline=_tl(0, 3))
    assert "IP-COURSE-02" not in _codes(r)
    r2 = _score_course(_OK_TEXT, timeline=_tl(0, 3.4))  # 3 天 + ~10h
    assert "IP-COURSE-02" not in _codes(r2)


def test_时间线未预取时间隔规则跳过():
    """纯文本调用方 / 无 encounter 上下文——宁漏不误。"""
    r = _score_course(_OK_TEXT, timeline=None)
    assert "IP-COURSE-02" not in _codes(r)
    r2 = _score_course(_OK_TEXT, timeline=CourseTimeline())  # loaded=False
    assert "IP-COURSE-02" not in _codes(r2)


def test_单条病程无间隔可言不扣():
    r = _score_course(_OK_TEXT, timeline=_tl(0))
    assert "IP-COURSE-02" not in _codes(r)


# ── IP-SENIOR-01 查房太简单 ──────────────────────────────────────────

def test_上级查房记录太简单被扣():
    ctx = build_context("同意目前治疗。", record_type="senior_round")
    r = score(_select_rubric("senior_round"), ctx)
    assert "IP-SENIOR-01" in _codes(r)
    assert r.score == 99.0  # 5 分大项扣 1


def test_正常查房记录不误伤():
    ctx = build_context(
        "主任医师查房：患者头晕较前好转，颈部僵硬减轻，查体无新增阳性体征。"
        "同意目前诊断与治疗方案，建议加用颈椎牵引，注意监测血压。",
        record_type="senior_round",
    )
    r = score(_select_rubric("senior_round"), ctx)
    assert "IP-SENIOR-01" not in _codes(r)


# ── 类型守卫：规则不越界到其他文书类型 ──────────────────────────────

def test_入院记录不触发病程规则():
    ctx = build_context("患者今日无特殊。", record_type="admission_note")
    r = score(_RUBRIC, ctx)
    assert not ({"IP-COURSE-01", "IP-COURSE-02", "IP-SENIOR-01"} & _codes(r))
