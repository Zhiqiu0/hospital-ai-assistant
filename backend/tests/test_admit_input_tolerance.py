"""接诊推送入参容错（2026-08-14 规范一致性核对发现）。

规范第 269 行白纸黑字承诺：「某项没有则不传，完全不影响流程」。
但实测发现，下面**任意一条**都会让整次接诊推送 ValidationError → 40004 被拒、
**患者根本进不了医生工作台**：

  · 体温推成 JSON 数字 36.5（HIS 里体征几乎都是数值列，这是最自然的写法）
  · 性别推国标代码 "1"（规范给的浙里智医对应字段 XB 本来就是 1/2/9）
  · 身份证推成数字（厂商可能存成数字列）
  · 初诊标志推 "2"（CZBZDM 国标里 2=复诊，而规范把类型写成 bool）

对照：visit_type 早就有中英文+数字的宽容映射，两个枚举字段策略不一致。
这里统一成同一套哲学——**选填字段的格式偏差不该打挂主流程**。
"""

import pytest

from app.his_adapter.models import AdmitPushRequest

BASE = dict(visit_id="V1", hospital_code="H1", patient_name="张三")


def _mk(**over):
    return AdmitPushRequest(**{**BASE, **over})


@pytest.mark.parametrize("raw,expected", [
    (36.5, "36.5"),
    (36, "36"),
    (36.0, "36"),      # 整数值浮点还原成 "36" 而不是 "36.0"
    ("36.5", "36.5"),
])
def test_体征数值转字符串(raw, expected):
    m = _mk(vitals={"temperature": raw})
    assert m.vitals.temperature == expected


@pytest.mark.parametrize("raw,expected", [
    ("male", "male"), ("1", "male"), ("男", "male"), ("M", "male"),
    ("female", "female"), ("2", "female"), ("女", "female"),
    ("unknown", "unknown"), ("9", "unknown"), (None, "unknown"),
    ("火星人", "unknown"),   # 识别不了降级，不拒收整条接诊
])
def test_性别宽容映射(raw, expected):
    assert _mk(gender=raw).gender == expected


@pytest.mark.parametrize("raw,expected", [
    (True, True), ("1", True), ("初诊", True),
    (False, False), ("2", False), ("复诊", False), ("0", False),
    ("说不清", None),   # 识别不了交给业务层按初诊兜底
])
def test_初诊标志宽容解析(raw, expected):
    assert _mk(is_first_visit=raw).is_first_visit is expected


def test_身份证手机号传数字也能收():
    m = _mk(id_card=110105194912310021, phone=13800138000)
    assert m.id_card == "110105194912310021"
    assert m.phone == "13800138000"


def test_一整包混合脏数据不打挂主流程():
    """联调首日最可能的形态：厂商各种字段都按 HIS 原生类型推。"""
    m = _mk(
        gender="1",
        id_card=110105194912310021,
        is_first_visit="2",
        vitals={"temperature": 38.5, "pulse": 96, "bp_systolic": 138},
    )
    assert m.gender == "male"
    assert m.is_first_visit is False
    assert m.vitals.temperature == "38.5" and m.vitals.pulse == "96"


def test_必填字段缺失仍然要拒():
    """防过度放宽：容错是给选填字段的格式，不是给必填字段的缺失。"""
    with pytest.raises(Exception):
        AdmitPushRequest(hospital_code="H1", patient_name="张三")  # 缺 visit_id
