"""DeductionRule.target_field 契约测试（L2 治本护栏）。

测试覆盖：
  1. 所有已注册 Rubric 的 DeductionRule.target_field 必须在白名单内（或为 None）
     —— rubric.py __post_init__ 已自动校验，本测试是显式断言层
  2. 白名单本身的命名规范（中文键 OR __xxx__ 不可写键）
  3. 故意构造非法 target_field 时 __post_init__ 必须抛 ValueError

历史背景：
  "逐条修复 → 写入病历"功能从 2026-04 起反复出 bug（中医舌脉、中医诊断合并行、
  治疗意见合并行），根因都是后端 field_name 跟前端章节映射对不齐 + 前端默默兜底追加
  把映射 bug 掩盖。本测试 + 前端 qcFieldMaps.test.ts 一起守住契约，
  让"忘补映射"在 CI 阶段红，而不是在医生屏幕上错位。
"""
from __future__ import annotations

import pytest

from app.services.qc_engine._writable_fields import (
    ALL_KNOWN_TARGET_FIELDS,
    NON_WRITABLE_FIELDS,
    WRITABLE_FIELDS,
)
from app.services.qc_engine.rubric import (
    DeductionRule,
    GradeThreshold,
    Rubric,
    RubricItem,
)
from app.services.qc_engine.rubrics.zj_inpatient_2021 import ZJ_INPATIENT_V2021
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023,
)


# 所有需要纳入契约检查的已注册 Rubric——新增 Rubric 时加到这里
_REGISTERED_RUBRICS = [
    ZJ_OUTPATIENT_EMERGENCY_V2023,
    ZJ_INPATIENT_V2021,
]


def test_all_target_fields_in_whitelist():
    """每个已注册 Rubric 的每条 DeductionRule.target_field 必须 None 或在白名单。

    这是 module import 时 __post_init__ 自动跑的逻辑，本测试是显式断言层，
    方便测试报告里一眼看到"哪条规则的 target_field 没补上"。
    """
    failures: list[str] = []
    for rubric in _REGISTERED_RUBRICS:
        for item in rubric.items:
            for rule in item.deduction_rules:
                if rule.target_field is None:
                    continue
                if rule.target_field not in ALL_KNOWN_TARGET_FIELDS:
                    failures.append(
                        f"{rubric.name} / {item.name} / {rule.code}: "
                        f"target_field={rule.target_field!r} 不在 _writable_fields 白名单"
                    )
    assert not failures, "存在 target_field 未注册到白名单：\n" + "\n".join(failures)


def test_writable_and_non_writable_no_overlap():
    """WRITABLE 与 NON_WRITABLE 必须互斥——一个字段不能既"可写"又"不可写"。"""
    overlap = WRITABLE_FIELDS & NON_WRITABLE_FIELDS
    assert not overlap, f"WRITABLE / NON_WRITABLE 集合有重叠：{overlap}"


def test_non_writable_naming_convention():
    """NON_WRITABLE_FIELDS 命名规范——必须是 __xxx__ 形式，区别于真业务字段。"""
    for field in NON_WRITABLE_FIELDS:
        assert field.startswith("__") and field.endswith("__"), (
            f"NON_WRITABLE 字段 {field!r} 不符合 __xxx__ 命名约定"
        )


def test_writable_fields_no_underscore_prefix():
    """WRITABLE_FIELDS 必须是真业务字段（中文键），不含 __xxx__ 形式。"""
    for field in WRITABLE_FIELDS:
        assert not field.startswith("__"), (
            f"WRITABLE 字段 {field!r} 不该以 __ 开头（那是 NON_WRITABLE 的命名）"
        )


def test_post_init_rejects_unknown_target_field():
    """__post_init__ 必须在构造时拦截未注册的 target_field——这是核心护栏。"""

    bad_rule = DeductionRule(
        code="TEST-BAD-01",
        description="测试用：故意填一个白名单外的字段",
        deduct_points=1,
        checker=lambda _ctx: False,
        target_field="这个字段绝不在白名单",
    )
    bad_item = RubricItem(
        name="测试项",
        max_points=10,
        description="",
        deduction_rules=(bad_rule,),
    )

    with pytest.raises(ValueError, match="未在 _writable_fields.py 白名单注册"):
        Rubric(
            name="测试 Rubric",
            version="test",
            record_scope="single",
            items=(bad_item,),
            grade_thresholds=(
                GradeThreshold(min_score=90, label="合格"),
                GradeThreshold(min_score=0, label="不合格"),
            ),
        )


def test_post_init_allows_none_target_field():
    """target_field=None 必须允许（适用大项与单字段 1:1 映射的旧场景）。"""

    ok_rule = DeductionRule(
        code="TEST-OK-01",
        description="测试用：target_field 为 None",
        deduct_points=1,
        checker=lambda _ctx: False,
        # 未传 target_field，默认 None
    )
    ok_item = RubricItem(
        name="测试项",
        max_points=10,
        description="",
        deduction_rules=(ok_rule,),
    )
    # 不抛 = 通过
    Rubric(
        name="测试 Rubric",
        version="test",
        record_scope="single",
        items=(ok_item,),
        grade_thresholds=(
            GradeThreshold(min_score=90, label="合格"),
            GradeThreshold(min_score=0, label="不合格"),
        ),
    )
