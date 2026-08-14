"""结构化生命体征数值守卫（2026-08-14 第八轮审计发现的红线漏洞）。

本项目的硬红线：**AI 绝不能编造体征/化验数值**（编一个体温，医生签发后随病历
回写 HIS，是医疗事故级别的问题）。

漏洞成因很有讽刺意味：
  prompts_voice 明确规定「生命体征只填 vital_signs 结构体，**严禁**出现在
  physical_exam 文字里」——这条为了字段归位而写的规则，恰好把体征数值从
  **受 output_guards 保护的文本**挪进了**守卫够不到的结构体**。
  于是语音结构化（医生最主要的输入路径）上只剩 prompt 里那句「未提及留空」
  的软约束，而 output_guards 的模块注释早就写明软约束不够、实测 LLM 仍会编
  「默认正常」的体征数值。

且旧守卫套上去也没用：vital_signs 的值是裸数值（"36.5"），匹配不上要求
「标记词+数值」的 _VITAL_TOKEN_RE，是空操作。本文件锁住新守卫的行为。
"""

import pytest

from app.services.ai.output_guards import (
    strip_unsubstantiated_vital_values,
    strip_unsubstantiated_vitals,
)


def test_旧的文本守卫对裸数值确实是空操作():
    """记录漏洞成因本身，防止有人误以为"套上旧守卫就行了"。"""
    transcript = "患者咳嗽三天，无发热"
    for bare in ("36.5", "72", "120/80"):
        assert strip_unsubstantiated_vitals(bare, transcript) == bare


def test_口述里没提的体征被剔除():
    transcript = "患者男性45岁，主诉咳嗽三天，无发热，胸片未见异常"
    vitals = {"temperature": "36.5", "pulse": "72"}

    kept, dropped = strip_unsubstantiated_vital_values(vitals, transcript)

    assert kept == {}
    assert set(dropped) == {"temperature", "pulse"}


def test_口述里真报过的数值要保留():
    """防过度剔除——医生真量了的值不能被守卫吃掉。"""
    transcript = "患者体温38.9度，脉搏96次每分，血压 140 90"
    vitals = {
        "temperature": "38.9",
        "pulse": "96",
        "bp_systolic": "140",
        "bp_diastolic": "90",
    }

    kept, dropped = strip_unsubstantiated_vital_values(vitals, transcript)

    assert dropped == []
    assert kept == vitals


def test_真假混杂时只剔除假的():
    """最常见的真实形态：医生只量了血压，LLM 顺手补了"正常"体温脉搏。"""
    transcript = "量了血压 120 80，患者诉头晕"
    vitals = {
        "bp_systolic": "120",
        "bp_diastolic": "80",
        "temperature": "36.5",  # 编的
        "pulse": "75",          # 编的
    }

    kept, dropped = strip_unsubstantiated_vital_values(vitals, transcript)

    assert kept == {"bp_systolic": "120", "bp_diastolic": "80"}
    assert set(dropped) == {"temperature", "pulse"}


def test_空值原样保留不算编造():
    transcript = "患者咳嗽"
    kept, dropped = strip_unsubstantiated_vital_values(
        {"temperature": "", "pulse": None}, transcript
    )
    assert dropped == []
    assert kept == {"temperature": "", "pulse": None}


def test_未知字段不参与判定():
    """未来 vital_signs 扩展非数值字段时不应被误删。"""
    transcript = "患者咳嗽"
    kept, dropped = strip_unsubstantiated_vital_values(
        {"note": "自诉不适", "temperature": "36.5"}, transcript
    )
    assert kept == {"note": "自诉不适"}
    assert dropped == ["temperature"]


def test_非字典输入不炸():
    assert strip_unsubstantiated_vital_values(None, "x") == ({}, [])
    assert strip_unsubstantiated_vital_values({}, "x") == ({}, [])


@pytest.mark.parametrize("spoken,value,should_keep", [
    ("体温三十六度五", "36.5", False),   # 中文数字：判无出处，有意剔除（宁可误删）
    ("身高170体重65", "170", True),
    ("血氧98%", "98", True),
])
def test_边界口述形态(spoken, value, should_keep):
    kept, _ = strip_unsubstantiated_vital_values({"temperature": value}, spoken)
    assert ("temperature" in kept) is should_keep
