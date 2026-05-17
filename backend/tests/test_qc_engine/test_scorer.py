"""评分器（scorer）单元测试。

锁死核心约束：
  - 起 100 扣分模型
  - 大项扣分上限保护（同项累积扣分不超过 max_points）
  - 单项否决短路（触发即扣 10、不再累积该项其他规则）
  - 规则 checker 抛异常时不阻断整体评分
"""
from dataclasses import replace

import pytest

from app.services.qc_engine.checker import RecordContext
from app.services.qc_engine.rubric import (
    DeductionRule,
    GradeThreshold,
    Rubric,
    RubricItem,
    VetoRule,
)
from app.services.qc_engine.scorer import score


def _ctx() -> RecordContext:
    """构造一个空上下文（不会触发任何 checker）。"""
    return RecordContext(record_text="", sections={})


def _always_true_rule(code: str, points: float = 1.0) -> DeductionRule:
    """每次都触发扣分的规则。"""
    return DeductionRule(
        code=code,
        description=f"always-true-{code}",
        deduct_points=points,
        checker=lambda _ctx: True,
    )


def _never_true_rule(code: str) -> DeductionRule:
    return DeductionRule(
        code=code,
        description=f"never-true-{code}",
        deduct_points=1.0,
        checker=lambda _ctx: False,
    )


def _veto(code: str) -> VetoRule:
    return VetoRule(code=code, description=f"veto-{code}", checker=lambda _ctx: True)


def _rubric(items, scope="single", thresholds=None):
    """构造一个最小 Rubric。"""
    return Rubric(
        name="test",
        version="1",
        record_scope=scope,
        items=tuple(items),
        grade_thresholds=tuple(thresholds or (
            GradeThreshold(90, "合格"),
            GradeThreshold(0, "不合格"),
        )),
    )


# ─── 基础扣分逻辑 ──────────────────────────────────────────────────


def test_no_rule_triggered_yields_100():
    """没有规则触发 → 满分 100。"""
    r = _rubric([RubricItem(name="x", max_points=100, description="", deduction_rules=())])
    rep = score(r, _ctx())
    assert rep.score == 100.0
    assert rep.total_deducted == 0
    assert rep.grade == "合格"


def test_single_rule_triggers_deducts_points():
    """单条规则触发 → 总分减去对应扣分。"""
    r = _rubric([
        RubricItem(name="x", max_points=10, description="",
                   deduction_rules=(_always_true_rule("R1", 3),)),
    ])
    rep = score(r, _ctx())
    assert rep.total_deducted == 3
    assert rep.score == 97
    assert len(rep.deductions) == 1
    assert rep.deductions[0].rule_code == "R1"


def test_multiple_rules_in_same_item_accumulate():
    """同项内多条规则触发 → 扣分累加。"""
    r = _rubric([
        RubricItem(name="x", max_points=20, description="", deduction_rules=(
            _always_true_rule("R1", 5),
            _always_true_rule("R2", 3),
        )),
    ])
    rep = score(r, _ctx())
    assert rep.total_deducted == 8
    assert rep.score == 92


def test_score_floor_is_zero():
    """扣分超过 100 → 兜底 0 分，不会负数。"""
    r = _rubric([
        RubricItem(name="x", max_points=100, description="", deduction_rules=(
            _always_true_rule("R1", 60),
            _always_true_rule("R2", 60),
        )),
    ])
    rep = score(r, _ctx())
    assert rep.score == 0  # 不是 -20


# ─── 大项扣分上限保护 ──────────────────────────────────────────────


def test_item_deduction_capped_at_max_points():
    """同一大项累积扣分不超过 max_points（PDF 隐含约束）。"""
    # 该项 max=10，但触发两条 +8 +5 = 13 → 实际只扣 10
    r = _rubric([
        RubricItem(name="x", max_points=10, description="", deduction_rules=(
            _always_true_rule("R1", 8),
            _always_true_rule("R2", 5),
        )),
    ])
    rep = score(r, _ctx())
    assert rep.total_deducted == 10  # 不是 13
    assert rep.score == 90
    # 扣分明细仍记 2 条（用户看得到原始触发情况），但累积值受上限
    assert len(rep.deductions) == 2
    assert rep.item_scores[0].deducted == 10


# ─── 单项否决（仅住院） ────────────────────────────────────────────


def test_veto_triggers_fixed_10_points_and_skips_other_rules():
    """单项否决触发 → 扣 10 分 + 跳过该项其他扣分规则（PDF 备注 6）。"""
    r = _rubric(
        items=[
            RubricItem(
                name="病案首页",
                max_points=10,
                description="",
                deduction_rules=(_always_true_rule("R1", 5),),  # 不该被触发
                veto_rules=(_veto("V1"),),
            ),
        ],
        scope="encounter",
        thresholds=[GradeThreshold(90, "甲"), GradeThreshold(80, "乙"), GradeThreshold(0, "丙")],
    )
    rep = score(r, _ctx())
    assert rep.total_deducted == 10
    assert rep.item_scores[0].veto_triggered is True
    assert rep.item_scores[0].deducted == 10
    # 只记 1 条 veto，普通规则不再触发
    assert len(rep.deductions) == 1
    assert rep.deductions[0].is_veto is True


def test_veto_deduction_also_capped_at_item_max_points():
    """单项否决扣 10，但若该大项 max_points<10 也受上限保护。"""
    r = _rubric(
        items=[
            RubricItem(
                name="医嘱单",
                max_points=2,
                description="",
                deduction_rules=(),
                veto_rules=(_veto("V1"),),
            ),
        ],
        scope="encounter",
        thresholds=[GradeThreshold(90, "甲"), GradeThreshold(80, "乙"), GradeThreshold(0, "丙")],
    )
    rep = score(r, _ctx())
    assert rep.item_scores[0].deducted == 2  # min(10, 2)


# ─── 规则崩溃容错 ─────────────────────────────────────────────────


def test_checker_exception_does_not_block_scoring():
    """规则 checker 自己抛异常 → 不阻断整体评分（视为未触发）。"""
    def bad_checker(_ctx):
        raise ValueError("规则 bug")
    bad_rule = DeductionRule(code="BAD", description="坏规则", deduct_points=5, checker=bad_checker)
    r = _rubric([
        RubricItem(name="x", max_points=10, description="",
                   deduction_rules=(bad_rule, _always_true_rule("R1", 3))),
    ])
    rep = score(r, _ctx())
    # 坏规则未触发，只扣好规则的 3 分
    assert rep.total_deducted == 3
    assert all(d.rule_code != "BAD" for d in rep.deductions)


# ─── 等级判定 ─────────────────────────────────────────────────────


def test_grade_label_follows_thresholds():
    """等级标签按 grade_thresholds 顺序判定。"""
    r = _rubric([RubricItem(name="x", max_points=20, description="",
                            deduction_rules=(_always_true_rule("R1", 15),))])
    rep = score(r, _ctx())
    # 扣 15 → 85 分 → 门诊"不合格"
    assert rep.score == 85
    assert rep.grade == "不合格"
    assert rep.passed is False


# ─── ScoreReport 序列化 ───────────────────────────────────────────


def test_score_report_to_dict_includes_item_breakdown():
    """ScoreReport.to_dict 必须包含每项扣分明细，前端按此渲染 PDF 四列表格。"""
    r = _rubric([RubricItem(name="主诉", max_points=5, description="测试",
                            deduction_rules=(_always_true_rule("OP-CC-01", 2),))])
    rep = score(r, _ctx())
    d = rep.to_dict()
    assert d["score"] == 98.0
    assert d["grade"] == "合格"
    assert len(d["items"]) == 1
    item = d["items"][0]
    assert item["name"] == "主诉"
    assert item["max_points"] == 5
    assert item["score"] == 3.0
    assert item["deducted"] == 2.0
    assert len(item["deductions"]) == 1
    assert item["deductions"][0]["rule_code"] == "OP-CC-01"
