"""Section / 占位符判定的单元测试。

防回归核心：is_filled() 是全项目唯一权威——必须把"占位符 / 空 / 真实内容"
三态行为严格锁定，新加占位符常量也要走这套测试。
"""
import pytest

from app.services.qc_engine.section import (
    MIN_FILLED_LENGTH,
    PLACEHOLDERS,
    Section,
)


# ─── is_filled 三态 ──────────────────────────────────────────────────


@pytest.mark.parametrize("raw_value", [
    "",
    " ",
    "\n\n",
    "   \t  ",
])
def test_empty_value_is_not_filled(raw_value):
    """空 / 纯空白 → 未填写。"""
    s = Section(name="测试", raw_value=raw_value)
    assert s.is_filled() is False


@pytest.mark.parametrize("placeholder", list(PLACEHOLDERS))
def test_placeholder_value_is_not_filled(placeholder):
    """所有占位符常量都视为未填写——治本核心断言。"""
    # 跳过"无"——它在 PLACEHOLDERS 里但 is_filled() 设计上让它通过
    # （医生用"无"表示否认是合法的，由 MIN_FILLED_LENGTH 兜底）
    s = Section(name="测试", raw_value=placeholder)
    if placeholder == "无":
        # "无" 长度 1 ≥ MIN_FILLED_LENGTH，但又在 PLACEHOLDERS——优先 PLACEHOLDERS
        assert s.is_filled() is False
    else:
        assert s.is_filled() is False


@pytest.mark.parametrize("placeholder", list(PLACEHOLDERS))
def test_placeholder_with_surrounding_whitespace_is_not_filled(placeholder):
    """占位符带前后空白也算占位符（is_filled 内部 strip 后再比对）。"""
    s = Section(name="测试", raw_value=f"  {placeholder}  ")
    assert s.is_filled() is False


@pytest.mark.parametrize("real_value", [
    "否认高血压、糖尿病等慢性病史",
    "舌淡红苔薄白",
    "脉弦",
    "急性起病，反复头痛 3 天",
    "暂无",  # 医生用"暂无"表示已查不在 PLACEHOLDERS 里——通过
])
def test_real_value_is_filled(real_value):
    """真实内容（含医生短句）必须 is_filled。"""
    s = Section(name="测试", raw_value=real_value)
    assert s.is_filled() is True, f"医生写的内容 {real_value!r} 应该算已填"


def test_min_filled_length_threshold():
    """单字符"否"也算已填（MIN_FILLED_LENGTH=1）。"""
    s = Section(name="测试", raw_value="否")
    assert s.is_filled() is True
    assert MIN_FILLED_LENGTH == 1


# ─── contains 辅助方法 ──────────────────────────────────────────────


def test_contains_only_when_filled():
    """contains 仅在 is_filled 时返回 True——占位符不算包含任何关键词。"""
    s = Section(name="测试", raw_value="[未填写，需补充]")
    assert s.contains("未填写") is False, "占位符的关键词不算医生填的"

    s = Section(name="测试", raw_value="患者头痛 3 天")
    assert s.contains("头痛") is True
    assert s.contains("发热") is False


def test_normalized_strips_whitespace():
    s = Section(name="测试", raw_value="  患者头痛  \n")
    assert s.normalized == "患者头痛"


# ─── Section 是不可变值对象 ─────────────────────────────────────────


def test_section_is_frozen():
    """Section 是 frozen dataclass——任何 mutation 应当抛 FrozenInstanceError。"""
    s = Section(name="测试", raw_value="x")
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        s.raw_value = "y"  # type: ignore
