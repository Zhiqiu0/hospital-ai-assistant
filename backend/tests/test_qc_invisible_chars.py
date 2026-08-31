# -*- coding: utf-8 -*-
"""不可见字符不得冒充「已填写」（2026-08-31 极端输入审计回归锁）。

背景：医生从 Word / PDF / 微信粘贴文字再删掉可见字符，字段里会残留一个零宽
空格。Python 的 str.strip() 清得掉全角空格与 NBSP，**清不掉零宽字符系**，于是
打印出来的法定病历上该栏是空白、而 QC 引擎判它「已填写」不扣分——医生据此
正常签发，完整性规则整条失效。这是静默损坏，事后查不出来。

本文件把三件事钉进 CI：
  1. 视觉上空白的字段一律判未填写；
  2. 医生真写的内容不受影响（别把「否认」这种合法短答误伤成未填写）；
  3. raw_value 原文不被系统改写——病历是法定记录，只是不拿不可见字符当证据。
"""
import pytest

from app.services.qc_engine.checker import RecordContext
from app.services.qc_engine.section import Section
from app.utils.text_clean import INVISIBLE_CHARS, strip_invisible

# 视觉上完全空白、却曾被判定为「已填写」的输入
BLANK_LOOKING = [
    "​",              # 单个零宽空格——阈值 MIN_FILLED_LENGTH=1，一个就够
    "​" * 3,
    "﻿﻿",        # BOM
    "⁠",              # 词连接符
    "‌‍",        # 零宽非连接符 + 零宽连接符
    "​ 　\n",     # 零宽 + 全角空格 + 换行的混合
]


@pytest.mark.parametrize("raw", BLANK_LOOKING)
def test_视觉空白的字段一律判未填写(raw: str):
    assert Section(name="主诉", raw_value=raw).is_filled() is False


@pytest.mark.parametrize("raw", ["咳嗽3天", "否认高血压、糖尿病史", "无"])
def test_医生真写的内容不受影响(raw: str):
    """「无」「否认」是医学语境下的合法已填写，不能被这次改动误伤。"""
    assert Section(name="既往史", raw_value=raw).is_filled() is True


def test_关键词匹配不再被夹在词中间的零宽字符打断():
    """粘贴带进来的零宽字符此前会切断「现病史须含起病时间」这类规则的匹配，
    造成医生明明写了却被扣分的误报。"""
    sec = Section(name="现病史", raw_value="咳​嗽3天，无发热")
    assert sec.contains("咳嗽") is True


def test_raw_value_原文不被改写():
    """系统不得静默改写医生写下的病历原文，剥离只作用于判定副本。"""
    raw = "咳​嗽3天"
    assert Section(name="主诉", raw_value=raw).raw_value == raw


@pytest.mark.parametrize("raw", BLANK_LOOKING)
def test_问诊字段判定与Section同口径(raw: str):
    """checker.inquiry_field_filled 是另一条独立判定路径，必须同口径，
    否则同一份内容在两处得出不同结论。"""
    class _C:
        # 只借这一个方法来测判定口径，不构造整个 RecordContext（它要一堆上下文）
        inquiry = {"chief_complaint": raw}
        inquiry_field_filled = RecordContext.inquiry_field_filled

    assert _C().inquiry_field_filled("chief_complaint") is False


def test_strip_invisible_保留正常内容():
    """只剥不可见字符，不做 strip、不压平换行——调用方各自决定。"""
    assert strip_invisible("  咳嗽\n3天  ") == "  咳嗽\n3天  "
    for ch in INVISIBLE_CHARS:
        assert strip_invisible(f"咳{ch}嗽") == "咳嗽"
