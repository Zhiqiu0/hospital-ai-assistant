"""患者身份信息字段校验（身份证号 / 手机号）。

设计原则（业内多层防御方案的"单一权威"层）：
  1. normalize 先于 validate：先去空白、连字符，末位 X 大写化，三态空值
     （None / "" / "   "）统一归一成 None，杜绝下游"同一身份证三种写法"。
  2. 校验算法严格度分级：strict 跑 GB 11643-1999 校验码；lenient 仅查格式，
     为未来 HIS 同步、历史数据迁移留接口形参。
  3. 所有 Pydantic 模型通过 Annotated 类型别名引入（IdCardStrict / Phone），
     永远只有一处定义，杜绝规则漂移。

参考标准：
  - GB 11643-1999《公民身份号码》末位校验码加权算法
  - 中国大陆手机号段：以 1 开头第二位 3-9（号段后续扩展不再细化，留覆盖空间）
"""
from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BeforeValidator

# ── 常量 ─────────────────────────────────────────────────────────────────────

# GB 11643-1999 加权因子（17 位身份证从左到右每位的权重）
_ID_CARD_WEIGHTS: tuple[int, ...] = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
# 加权和 mod 11 → 校验码字符的映射表（index 即余数 0..10）
_ID_CARD_CHECKSUM_MAP: tuple[str, ...] = ("1", "0", "X", "9", "8", "7", "6", "5", "4", "3", "2")

# 身份证基础格式：18 位，前 17 位数字，末位数字或大写 X
# （normalize 已经把小写 x 转大写、空格连字符去掉，到这里只接受标准形态）
_ID_CARD_FORMAT_RE = re.compile(r"^\d{17}[\dX]$")

# 中国大陆手机号：1 开头 + 第二位 3-9 + 后 9 位数字
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

# 校验模式类型别名
ValidateMode = Literal["strict", "lenient"]


# ── 标准化函数 ────────────────────────────────────────────────────────────────

def normalize_id_card(value: str | None) -> str | None:
    """身份证标准化：去除空白与连字符，末位 x → X，空值三态归一。

    输入 "11010519491231 002x" / "  " / None / "" 都会得到合理结果：
      - 非字符串：原样返回（Pydantic 后续步骤会再报类型错）
      - 空/纯空白：返回 None（视为未填，选填字段直接放行）
      - 含空白/连字符：去掉后大写化末位
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    # 去除所有空白字符与连字符（用户从 Excel 复制粘贴常带这些）
    cleaned = re.sub(r"[\s\-]", "", value)
    if not cleaned:
        return None
    # 末位 x 大写化（GB 11643 规定校验码若为 10 写作 X，大小写在用户输入里都见过）
    if cleaned[-1] in "xX":
        cleaned = cleaned[:-1] + "X"
    return cleaned


def normalize_phone(value: str | None) -> str | None:
    """手机号标准化：去除所有空白与常见分隔符（空格、连字符、括号），空值归一。

    支持输入 "138 0013 8000" / "+86-138-0013-8000" / "(138) 0013-8000" 等用户
    输入形态。+86 国家码会被剥掉（数据库存 11 位纯数字）。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    # 去除所有非数字字符
    cleaned = re.sub(r"\D", "", value)
    if not cleaned:
        return None
    # 剥离国家码 86（部分前端表单或 HIS 接口会带）
    if cleaned.startswith("86") and len(cleaned) == 13:
        cleaned = cleaned[2:]
    return cleaned


# ── 校验函数 ────────────────────────────────────────────────────────────────

def _compute_id_card_checksum(first_17: str) -> str:
    """根据 GB 11643-1999 算法对前 17 位计算第 18 位校验码。"""
    total = sum(int(ch) * w for ch, w in zip(first_17, _ID_CARD_WEIGHTS))
    return _ID_CARD_CHECKSUM_MAP[total % 11]


def validate_id_card(value: str | None, mode: ValidateMode = "strict") -> str | None:
    """身份证号校验。

    Args:
        value: 已经过 normalize_id_card 处理的字符串（或 None）
        mode:
            - "strict"  : 格式 + 出生日期合法性 + GB 11643 校验码（推荐默认）
            - "lenient" : 仅查格式与出生日期合法性，跳过校验码
                          预留给历史数据迁移、HIS 同步等场景，当前无调用方

    Returns:
        校验通过的字符串原样返回；value 为 None 时直接返回 None（选填语义）

    Raises:
        ValueError: 任一校验失败时抛出，Pydantic 会自动转 422 响应
    """
    if value is None:
        return None
    if not _ID_CARD_FORMAT_RE.match(value):
        raise ValueError("身份证号格式错误：应为 18 位（17 位数字 + 1 位数字或 X）")

    # 第 7-14 位是出生日期（YYYYMMDD），校验日期本身的合法性
    # 错位/打字典型错误（如 19901301）能在这一步挡住，比纯校验码更友好
    birth_str = value[6:14]
    try:
        year = int(birth_str[0:4])
        month = int(birth_str[4:6])
        day = int(birth_str[6:8])
        # 简单范围检查，避免 import datetime 但又能挡住 9999/13/32 这类
        # year 下限 1880 是医疗档案的合理上界（长寿患者档案场景），上限 2099 留余量
        if not (1880 <= year <= 2099 and 1 <= month <= 12 and 1 <= day <= 31):
            raise ValueError
    except ValueError as exc:
        raise ValueError(f"身份证号内含出生日期不合法：{birth_str}") from exc

    if mode == "strict":
        expected = _compute_id_card_checksum(value[:17])
        if value[17] != expected:
            raise ValueError("身份证号校验码错误（GB 11643-1999），请检查是否输错")

    return value


def validate_phone(value: str | None) -> str | None:
    """中国大陆手机号校验。

    号段判断仅查 1[3-9] 开头，号段越细维护成本越高（号段年年扩），这套足够
    挡住"6 位"、"全 0"、"座机号"这类明显错误。

    Args:
        value: 已经过 normalize_phone 处理的字符串（或 None）
    """
    if value is None:
        return None
    if not _PHONE_RE.match(value):
        raise ValueError("手机号格式错误：应为 11 位、以 1[3-9] 开头的中国大陆手机号")
    return value


def extract_birth_date_from_id_card(id_card: str) -> tuple[int, int, int] | None:
    """从身份证号提取出生日期，供 service 层做跨字段一致性校验。

    Args:
        id_card: 已经 normalize + validate 通过的 18 位身份证号

    Returns:
        (year, month, day)；非法身份证（不应该走到这里）返回 None
    """
    if not id_card or len(id_card) != 18:
        return None
    try:
        year = int(id_card[6:10])
        month = int(id_card[10:12])
        day = int(id_card[12:14])
        return (year, month, day)
    except ValueError:
        return None


# ── Pydantic 类型别名（schemas 引用入口）─────────────────────────────────────

# strict 模式：医生手工录入患者时使用（必须过校验码）
IdCardStrict = Annotated[
    str | None,
    BeforeValidator(normalize_id_card),
    AfterValidator(lambda v: validate_id_card(v, mode="strict")),
]

# lenient 模式：预留给 HIS 同步等场景，当前未使用，但提前定义好让未来迁移零成本
IdCardLenient = Annotated[
    str | None,
    BeforeValidator(normalize_id_card),
    AfterValidator(lambda v: validate_id_card(v, mode="lenient")),
]

# 手机号类型别名（无模式区分，统一严格校验）
Phone = Annotated[
    str | None,
    BeforeValidator(normalize_phone),
    AfterValidator(validate_phone),
]
