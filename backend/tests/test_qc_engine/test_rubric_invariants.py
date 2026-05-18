"""Rubric 数据结构不变量测试。

锁死核心约束：
  - 等级阈值必须按 min_score 降序
  - 最低等级 min_score 必须为 0（兜底）
  - 门诊 Rubric 不允许有 VetoRule（单项否决仅住院）
  - 浙江省门急诊 Rubric 总分必须为 100
"""
import pytest

from app.services.qc_engine.rubric import (
    DeductionRule,
    GradeThreshold,
    Rubric,
    RubricItem,
    VetoRule,
)
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023,
)


def _dummy_checker(_ctx):
    return False


def _dummy_rule(code="X"):
    return DeductionRule(code=code, description="测试", deduct_points=1, checker=_dummy_checker)


def _dummy_veto(code="V"):
    return VetoRule(code=code, description="测试", checker=_dummy_checker)


# ─── Rubric 不变量 ──────────────────────────────────────────────────


def test_grade_thresholds_must_be_descending():
    """等级阈值升序排列会被 __post_init__ 拒绝。"""
    with pytest.raises(ValueError, match="降序"):
        Rubric(
            name="测试",
            version="1",
            record_scope="single",
            items=(),
            grade_thresholds=(
                GradeThreshold(0, "丙"),
                GradeThreshold(90, "甲"),  # 顺序错误
            ),
        )


def test_lowest_threshold_must_be_zero():
    """最低 min_score 必须为 0（兜底）。"""
    with pytest.raises(ValueError, match="兜底所有分数"):
        Rubric(
            name="测试",
            version="1",
            record_scope="single",
            items=(),
            grade_thresholds=(GradeThreshold(90, "合格"),),  # 缺兜底
        )


def test_single_scope_cannot_have_veto_rules():
    """门诊（single scope）不允许 veto_rules——构造时即报错。"""
    with pytest.raises(ValueError, match="不允许 veto_rules"):
        Rubric(
            name="测试门诊",
            version="1",
            record_scope="single",
            items=(
                RubricItem(
                    name="项",
                    max_points=10,
                    description="",
                    deduction_rules=(),
                    veto_rules=(_dummy_veto(),),  # 门诊放 veto 应报错
                ),
            ),
            grade_thresholds=(GradeThreshold(0, "不合格"),),
        )


def test_encounter_scope_allows_veto_rules():
    """住院（encounter scope）允许 veto_rules。"""
    r = Rubric(
        name="测试住院",
        version="1",
        record_scope="encounter",
        items=(
            RubricItem(
                name="项",
                max_points=10,
                description="",
                deduction_rules=(),
                veto_rules=(_dummy_veto(),),
            ),
        ),
        grade_thresholds=(GradeThreshold(0, "丙"),),
    )
    assert r.items[0].veto_rules


# ─── 等级判定 ───────────────────────────────────────────────────────


def test_grade_for_outpatient_boundary():
    """门诊 PDF 注 5：≥90 合格 / <90 不合格。"""
    r = ZJ_OUTPATIENT_EMERGENCY_V2023
    assert r.grade_for(100) == "合格"
    assert r.grade_for(90) == "合格"
    assert r.grade_for(89.99) == "不合格"
    assert r.grade_for(0) == "不合格"
    assert r.passed(90) is True
    assert r.passed(89.99) is False


def test_outpatient_rubric_total_points_is_100():
    """门急诊 PDF 11 大项合计必须 100 分。"""
    assert ZJ_OUTPATIENT_EMERGENCY_V2023.total_points == 100


def test_outpatient_rubric_has_11_items():
    """PDF 11 大项必须全部映射进 Rubric。"""
    assert len(ZJ_OUTPATIENT_EMERGENCY_V2023.items) == 11


def test_outpatient_rubric_item_names_match_pdf():
    """大项名称对照 PDF 1:1（防 typo / 漏项）。"""
    actual = [item.name for item in ZJ_OUTPATIENT_EMERGENCY_V2023.items]
    expected = [
        "基本要求",
        "患者基础信息",
        "主诉",
        "现病史",
        "既往史",
        "体格检查",
        "辅助检查及结果",
        "诊断",
        "治疗意见及措施",
        "知情同意书",
        "其他（急诊补充）",
    ]
    assert actual == expected, f"PDF 大项映射不全：{actual} vs {expected}"


def test_outpatient_rubric_max_points_match_pdf():
    """大项分值对照 PDF 1:1。"""
    expected_points = {
        "基本要求": 5,
        "患者基础信息": 10,
        "主诉": 5,
        "现病史": 20,
        "既往史": 10,
        "体格检查": 10,
        "辅助检查及结果": 5,
        "诊断": 10,
        "治疗意见及措施": 10,
        "知情同意书": 5,
        "其他（急诊补充）": 10,
    }
    for item in ZJ_OUTPATIENT_EMERGENCY_V2023.items:
        assert item.max_points == expected_points[item.name], \
            f"大项 {item.name} 分值应为 {expected_points[item.name]}，当前 {item.max_points}"
