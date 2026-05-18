"""身份证 / 手机号校验单元测试。

加载 tests/fixtures/identity_cases.json 中的共享用例（前端 vitest 也读这份），
保证前后端校验规则在同一组用例下输出一致，杜绝规则漂移。

覆盖：
  - 合法 strict 用例（GB 11643 校验码通过）
  - 校验码错误（lenient 通过但 strict 拒绝）
  - 格式错误（任何模式拒绝）
  - 出生日期非法（13 月 / 2 月 30 日 / 1899 年等）
  - normalize 行为（去空格、连字符、大小写 X、+86 国家码）
  - 空值三态归一
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.validators.identity import (
    IdCardLenient,
    IdCardStrict,
    Phone,
    extract_birth_date_from_id_card,
    normalize_id_card,
    normalize_phone,
    validate_id_card,
    validate_phone,
)
from pydantic import BaseModel, ValidationError


# ── fixture 加载 ──────────────────────────────────────────────────────────────

# fixture 放仓库根 shared/，前后端共享一份，杜绝规则漂移
_FIXTURE_PATH = Path(__file__).resolve().parents[2] / "shared" / "identity_cases.json"
_CASES = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


# ── 身份证：strict 模式合法用例 ───────────────────────────────────────────────

@pytest.mark.parametrize("value", _CASES["id_card"]["valid_strict"])
def test_id_card_strict_valid(value: str) -> None:
    """fixture 里的合法号码 strict 模式必须全部通过。"""
    assert validate_id_card(value, mode="strict") == value


# ── 身份证：校验码错误（strict 拒绝、lenient 通过）─────────────────────────────

@pytest.mark.parametrize("value", _CASES["id_card"]["invalid_checksum"])
def test_id_card_strict_rejects_bad_checksum(value: str) -> None:
    """校验码错的号码必须被 strict 模式拒绝（防全 1、错位、打字错）。"""
    with pytest.raises(ValueError, match="校验码"):
        validate_id_card(value, mode="strict")


@pytest.mark.parametrize("value", _CASES["id_card"]["invalid_checksum"])
def test_id_card_lenient_accepts_bad_checksum(value: str) -> None:
    """lenient 模式仅查格式，校验码错也放行（为 HIS 同步预留）。"""
    assert validate_id_card(value, mode="lenient") == value


# ── 身份证：格式错误（任何模式都拒绝）─────────────────────────────────────────

@pytest.mark.parametrize("value", _CASES["id_card"]["invalid_format"])
def test_id_card_format_invalid_any_mode(value: str) -> None:
    """长度不对、字符集不对在 normalize 后任何模式都该挂。"""
    normalized = normalize_id_card(value)
    with pytest.raises(ValueError):
        validate_id_card(normalized, mode="strict")
    with pytest.raises(ValueError):
        validate_id_card(normalized, mode="lenient")


# ── 身份证：出生日期非法 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("value", _CASES["id_card"]["invalid_birth_date"])
def test_id_card_invalid_birth_date(value: str) -> None:
    """出生日期不合法（13 月 / 32 日 / 1899 / 2100）拒绝。"""
    with pytest.raises(ValueError, match="出生日期"):
        validate_id_card(value, mode="strict")


# ── normalize 行为 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "case",
    _CASES["id_card"]["normalize"],
    ids=lambda c: f"{c['input']!r}->{c['expected']!r}",
)
def test_id_card_normalize(case: dict) -> None:
    """空格 / 连字符 / 小写 x / 空值三态都归一成期望形态。"""
    assert normalize_id_card(case["input"]) == case["expected"]


def test_id_card_none_passes_through() -> None:
    """None 在选填语义下直接通过校验。"""
    assert validate_id_card(None, mode="strict") is None
    assert validate_id_card(None, mode="lenient") is None


# ── 手机号 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", _CASES["phone"]["valid"])
def test_phone_valid(value: str) -> None:
    """合法手机号通过。"""
    assert validate_phone(value) == value


@pytest.mark.parametrize("value", _CASES["phone"]["invalid"])
def test_phone_invalid(value: str) -> None:
    """非法手机号（位数错 / 字母 / 非 1 开头 / 第二位 1-2）拒绝。"""
    normalized = normalize_phone(value)
    with pytest.raises(ValueError):
        validate_phone(normalized)


@pytest.mark.parametrize(
    "case",
    _CASES["phone"]["normalize"],
    ids=lambda c: f"{c['input']!r}->{c['expected']!r}",
)
def test_phone_normalize(case: dict) -> None:
    """空格 / 连字符 / +86 国家码 / 括号都被剥成纯 11 位数字。"""
    assert normalize_phone(case["input"]) == case["expected"]


def test_phone_none_passes_through() -> None:
    """None 直接通过（选填字段）。"""
    assert validate_phone(None) is None


# ── Pydantic 类型别名集成测试 ─────────────────────────────────────────────────

class _DemoPatient(BaseModel):
    """临时 Pydantic 模型，验证类型别名在真实 schema 路径上工作正常。"""

    id_card: IdCardStrict = None
    phone: Phone = None


def test_pydantic_alias_normalize_and_validate() -> None:
    """通过 Pydantic 模型校验链：normalize → validate 自动串联。"""
    m = _DemoPatient(id_card="11010519491231002x", phone="138-0013-8000")
    assert m.id_card == "11010519491231002X"
    assert m.phone == "13800138000"


def test_pydantic_alias_raises_validation_error() -> None:
    """Pydantic 校验失败时抛 ValidationError（FastAPI 自动转 422）。"""
    with pytest.raises(ValidationError):
        _DemoPatient(id_card="11111111111111111X")
    with pytest.raises(ValidationError):
        _DemoPatient(phone="12345")


def test_pydantic_alias_accepts_none_and_empty() -> None:
    """空值三态在 Pydantic 链路上都归一为 None。"""
    assert _DemoPatient(id_card=None, phone=None).id_card is None
    assert _DemoPatient(id_card="", phone="").phone is None
    assert _DemoPatient(id_card="   ", phone="   ").id_card is None


# ── extract_birth_date_from_id_card ──────────────────────────────────────────

def test_extract_birth_date() -> None:
    """从身份证号提取出生日期供 service 层做跨字段一致性校验。"""
    assert extract_birth_date_from_id_card("11010519491231002X") == (1949, 12, 31)
    assert extract_birth_date_from_id_card("310101199001011234") == (1990, 1, 1)
    assert extract_birth_date_from_id_card("") is None
    assert extract_birth_date_from_id_card("invalid") is None


# ── service 层跨字段一致性测试 ──────────────────────────────────────────────

from datetime import date  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from app.services.patient_service import _assert_id_card_birth_date_consistent  # noqa: E402


def test_cross_field_consistent_passes() -> None:
    """身份证内嵌日期与 birth_date 一致时不抛异常。"""
    _assert_id_card_birth_date_consistent("11010519491231002X", date(1949, 12, 31))
    _assert_id_card_birth_date_consistent("310101199001011234", date(1990, 1, 1))


def test_cross_field_inconsistent_raises_422() -> None:
    """两边都填了但不一致 → HTTPException 422，前端可读到具体提示。"""
    with pytest.raises(HTTPException) as exc_info:
        _assert_id_card_birth_date_consistent("310101199001011234", date(1990, 5, 20))
    assert exc_info.value.status_code == 422
    assert "身份证号与出生日期不符" in exc_info.value.detail


def test_cross_field_one_side_none_passes() -> None:
    """任一为空时无法对比，直接放行（单字段校验已由 Pydantic 层兜底）。"""
    _assert_id_card_birth_date_consistent(None, date(1990, 1, 1))
    _assert_id_card_birth_date_consistent("310101199001011234", None)
    _assert_id_card_birth_date_consistent(None, None)
