"""LLM 输出后处理守卫（services/ai/output_guards.py）

2026-06-11 治本：医疗真实性不能只靠 prompt 约束（软约束，LLM 服从度有限，
实测补全仍会编造"默认正常"生命体征数值）。业界成熟做法是在 LLM 输出侧加
确定性的后处理校验（output guardrail）——本模块实现其中最关键的一条：

  **数值溯源校验**：生命体征类数值（T/P/R/BP/SpO2）必须能在医生录入的
  原始数据（问诊字段 + 病历草稿）里找到出处，找不到的视为编造、整个
  token 从输出中剔除，只保留无数值的描述性文字。

设计权衡：
  - 只拦"带数值的体征 token"，不拦描述性文字（"神志清，查体合作"这类
    规范描述是允许 LLM 推断的，见 QC_FIX_BATCH_PROMPT 约束 6）
  - 数字匹配按"字面出现"判定（36.5 必须以 36.5 出现过），宁可误删
    不可漏放——删掉的字段医生可以手填，编造的数值医生可能直接签发
"""

from __future__ import annotations

import re

# 生命体征 token：标记（T/P/R/BP/HR/SpO2）+ 可选冒号 + 数值（可带小数、收缩/舒张压
# 的斜杠）+ 可选单位。覆盖 "T:36.5℃" / "T 36.5℃" / "BP 120/80mmHg" / "SpO₂ 98%" 等写法
_VITAL_TOKEN_RE = re.compile(
    r"(?:T|P|R|BP|HR|SpO[2₂])\s*[:：]?\s*"
    r"\d{1,3}(?:\.\d+)?(?:\s*/\s*\d{1,3})?"
    r"\s*(?:℃|°C|次/分|mmHg|%)?",
)

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _extract_numbers(text: str) -> set[str]:
    """提取文本中所有数字串（含小数），作为"有出处数值"的字面集合。"""
    return set(_NUM_RE.findall(text or ""))


def strip_unsubstantiated_vitals(value: str, source_text: str) -> str:
    """剔除 value 中数值无出处的生命体征 token，返回清理后的文本。

    Args:
        value:       LLM 给出的字段修复文本
        source_text: 医生录入的全部原始数据拼接（问诊字段 + 病历草稿），
                     数值只要在这里出现过就算"有出处"

    Returns:
        清理后的文本；若全部内容都被剔除则返回空串（调用方应丢弃该条）
    """
    if not value:
        return value
    source_numbers = _extract_numbers(source_text)

    def _replace(match: re.Match) -> str:
        token_numbers = _NUM_RE.findall(match.group(0))
        # token 里所有数字都有出处 → 保留；任一数字查无出处 → 整个 token 剔除
        if token_numbers and all(n in source_numbers for n in token_numbers):
            return match.group(0)
        return ""

    cleaned = _VITAL_TOKEN_RE.sub(_replace, value)
    if cleaned == value:
        return value

    # 清理剔除后残留的悬空分隔符："，，" / 行首逗号 / "，。" 等
    cleaned = re.sub(r"[，,、;；]\s*(?=[，,、;；。])", "", cleaned)  # 连续分隔符合并
    cleaned = re.sub(r"(^|\n)[，,、;；。\s]+", r"\1", cleaned)        # 行首悬空标点
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip("，,、;； \t")
