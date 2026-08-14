"""safe_format 回归测试（2026-08-14 第七轮审计）。

核心不变量：**模板来自管理员在「提示词管理」页手写的内容，它再烂也不能把端点打挂**。
此前 safe_format 直接 str.format，且各调用点这一行都在 try 之外——
管理员写错一个占位符，追问建议 / 检查建议 / 诊断建议 / 质控 / 批量补全
六处调用同时恒 500，全院医生的 AI 功能一起瘫痪。
"""

from app.services.ai.ai_utils import safe_format


def test_正常占位符照常替换():
    assert safe_format("主诉：{chief}", chief="头痛") == "主诉：头痛"


def test_值统一转字符串():
    assert safe_format("体温 {t}", t=38.5) == "体温 38.5"


def test_未知占位符不抛异常而是退回原模板():
    """管理员写了 {patient_name}，但调用点没提供这个变量。"""
    tpl = "主诉 {chief}，患者 {patient_name}"
    assert safe_format(tpl, chief="头痛") == tpl


def test_模板里的裸花括号不抛异常():
    """提示词里贴了 JSON 示例（很常见），不该让整个功能挂掉。"""
    tpl = '按此格式输出：{"diagnosis": "x"}'
    assert safe_format(tpl, chief="头痛") == tpl


def test_单个左花括号不抛异常():
    tpl = "计算 a { b"
    assert safe_format(tpl, chief="x") == tpl


def test_位置占位符不抛异常():
    """{} / {0} 这类位置占位符在 kwargs 调用下会 IndexError。"""
    tpl = "占位 {} 和 {0}"
    assert safe_format(tpl, chief="x") == tpl


def test_值里的花括号原样保留():
    """医生正文里的 {"WBC":9.8} 不该被转义成 {{"WBC":9.8}}（2026-08-12 已修，防回归）。"""
    assert safe_format("化验：{v}", v='{"WBC":9.8}') == '化验：{"WBC":9.8}'
