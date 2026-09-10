# -*- coding: utf-8 -*-
"""体征全角数字归一化（2026-09-10 第 18 轮编码边界审计）。

抓的问题：中文输入法全角态敲出的 ３６．５ 能被 Python float() 解析（float
接受 Unicode 数字），于是通过生理极限校验后**原样落库**——全角串随后进
病历正文与 HIS 回写，厂商侧解析和 QC 数值提取都认不出。

修法：vital_limits.normalize_vital_text 单一来源归一（全角数字/小数点/
正负号→半角），问诊校验器先归一再校验，落库值=归一化值。
住院路径（VitalSignIn）是强类型 float/int，落库数字，本就无此病。
"""
from app.schemas.encounter import InquiryInputUpdate
from app.services.vital_limits import normalize_vital_text, parse_vital_number


def test_全角体温归一成半角落库():
    r = InquiryInputUpdate(temperature="３６．５")
    assert r.temperature == "36.5", f"全角未归一，落库值：{r.temperature!r}"


def test_全角出界值仍被拒():
    import pytest
    with pytest.raises(Exception) as ei:
        InquiryInputUpdate(temperature="４６")  # 46℃ 超生理极限
    assert "生理极限" in str(ei.value)


def test_半角正常值不受影响():
    r = InquiryInputUpdate(temperature="36.5", bp_systolic="120", bp_diastolic="80")
    assert r.temperature == "36.5"
    assert r.bp_systolic == "120"


def test_带单位自由文本保留但数字归一():
    # 自由文本放行不校验，但其中的全角数字也归一（HIS/QC 才认得）
    assert normalize_vital_text("３６．５℃ 腋温") == "36.5℃ 腋温"
    # 纯文本备注原样
    assert normalize_vital_text("拒测") == "拒测"


def test_parse对全角与半角同值():
    assert parse_vital_number("３６．５") == parse_vital_number("36.5") == 36.5
