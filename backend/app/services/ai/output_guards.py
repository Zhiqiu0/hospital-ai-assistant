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

from app.services.ai.record_schemas import PLACEHOLDER

# 生命体征 token：标记 + 可选冒号 + 数值（可带小数、收缩/舒张压的斜杠）+ 可选单位。
# 标记同时覆盖拉丁缩写（T/P/R/BP/HR/SpO2）与中文写法（体温/脉搏/心率/呼吸/血压/
# 血氧/血氧饱和度）——2026-08-11 审计修复：原正则只认拉丁缩写，"体温36.8℃"这类
# 中文写法的编造数值会直接绕过守卫放行，破坏 AI 数值真实性红线。
_VITAL_TOKEN_RE = re.compile(
    r"(?:T|P|R|BP|HR|SpO[2₂]|体温|脉搏|心率|呼吸|血压|血氧饱和度|血氧)\s*[:：]?\s*"
    r"\d{1,3}(?:\.\d+)?(?:\s*/\s*\d{1,3})?"
    r"\s*(?:℃|°C|次/分|mmHg|%)?",
)

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _extract_numbers(text: str) -> set[str]:
    """提取文本中所有数字串（含小数），作为"有出处数值"的字面集合。

    口语小数归一（2026-08-20 生产端到端冒烟发现）：医生口述"体温36度8/36点8"，
    转写原文没有字面"36.8"，LLM 规范化输出的 36.8 会被误判无出处而剔除
    （血压"135的82"反而能活，因为是两个独立整数）。把"数字度/点数字"归一成
    小数形式一并加入集合——只增不减，真编造的数值（原文完全没有）仍会被剔。
    """
    text = text or ""
    numbers = set(_NUM_RE.findall(text))
    for m in re.finditer(r"(\d+)[度点](\d+)", text):
        numbers.add(f"{m.group(1)}.{m.group(2)}")
    return numbers


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


# ── 结构化生命体征守卫（2026-08-14 第八轮审计）─────────────────────────────
#
# 上面那个 strip_unsubstantiated_vitals 只能守**文本**里的体征 token
# （形如「体温36.5℃」，标记词 + 数值）。但语音结构化接口
# （/ai/voice-structure）返回的是 inquiry.vital_signs 结构体，值是**裸数值**：
#     {"temperature": "36.5", "pulse": "72", "bp_systolic": "120"}
# 裸数值匹配不上 _VITAL_TOKEN_RE，把旧守卫套上去是**空操作**（实测确认）。
#
# 更要命的是成因：prompts_voice 里明确规定「生命体征只填 vital_signs 结构体，
# **严禁**出现在 physical_exam 文字里」——这条为了字段归位而写的规则，
# 恰好把体征数值从**受守卫保护的文本**挪进了**守卫够不到的结构体**。
# 于是 LLM 编一个「默认正常」的体温 36.5，就直接落进医生工作台的体温输入框，
# 医生签发后连同病历一起回写 HIS。而语音正是医生最主要的输入路径。
#
# 判定沿用同一套哲学：数值必须在医生口述原文里**字面出现**才保留。
# 已知代价：医生说「血压一百二十」这类中文数字会被判无出处而剔除。
# 这是有意的——剔除了医生可以手填，编造的数值医生可能直接签发。

# vital_signs 里需要校验的数值字段（与 prompts_voice 的输出契约一致）
_VITAL_VALUE_KEYS = (
    "temperature", "pulse", "respiration",
    "bp_systolic", "bp_diastolic", "spo2", "height", "weight",
)


def strip_unsubstantiated_vital_values(
    vitals: dict, source_text: str
) -> tuple[dict, list[str]]:
    """剔除 vital_signs 结构体里数值无出处的字段。

    Args:
        vitals:      LLM 返回的 vital_signs 字典（值为字符串裸数值）
        source_text: 医生口述转写原文，数值在这里字面出现过才算有出处

    Returns:
        (清理后的 vitals, 被剔除的字段名列表)
    """
    if not isinstance(vitals, dict) or not vitals:
        return (vitals if isinstance(vitals, dict) else {}), []

    source_numbers = _extract_numbers(source_text)
    cleaned: dict = {}
    dropped: list[str] = []

    for key, value in vitals.items():
        text = str(value).strip() if value is not None else ""
        if key not in _VITAL_VALUE_KEYS or not text:
            # 非数值字段（未来可能扩展）与空值原样保留，不做判断
            cleaned[key] = value
            continue
        numbers = _NUM_RE.findall(text)
        if numbers and all(n in source_numbers for n in numbers):
            cleaned[key] = value
        else:
            dropped.append(key)

    return cleaned, dropped


# ─── 照抄类字段的"源为空则输出必空"守卫（2026-09-02 AI 输出安全面）─────────
#
# prompt 明确要求诊断、治则治法、处理意见（药名剂量用法）**严格照抄，不改写**
# （OUTPATIENT_STYLE_RULES 第 2 条）。既然是照抄，就能做一条零误伤的确定性
# 校验：**医生没录入的照抄字段，AI 输出里也必须是空/占位符**——凭空冒出内容
# 只可能是编造或被诱导。
#
# 为什么需要它：实测把伪造的「# 系统指令」段落放进现病史，模型三条照做——
# 诊断写成"体检未见异常，无需治疗"（主诉是咳嗽3天）、开出十倍剂量的阿莫西林、
# 注意事项栏写进"本院对本次诊疗结果不承担任何责任"。先在 prompt 侧加了定界符
# 与显式声明（data/instruction 隔离），**复验时三条仍然全中**——这正是本模块
# 开头那句话的又一次印证：软约束不可靠，医疗真实性必须落在输出侧的确定性守卫上。
#
# 这条守卫同时覆盖另一类更常见的风险：没有任何注入，模型自己按常见病"补全"出
# 一个诊断和一套用药，而医生根本没写——那同样是编造，且看起来完全合理，最容易
# 被直接签发。
#
# 刻意不判断内容"对不对"（无法确定性判定），只判断"医生给没给"。

# AI 输出字段 → 医生录入的同名源字段。两侧同名，但显式列出以免加字段时漏配。
COPY_THROUGH_FIELDS: dict[str, str] = {
    "western_diagnosis": "western_diagnosis",
    "tcm_disease_diagnosis": "tcm_disease_diagnosis",
    "tcm_syndrome_diagnosis": "tcm_syndrome_diagnosis",
    "treatment_method": "treatment_method",
    "treatment_plan": "treatment_plan",
    "precautions": "precautions",
    "initial_impression": "initial_impression",
}


def _is_blank(value) -> bool:
    """医生这一栏到底有没有填——占位符按"没填"算。"""
    if value is None:
        return True
    text = str(value).strip()
    return not text or text == PLACEHOLDER


def strip_unsourced_copy_fields(result: dict, req) -> list[str]:
    """把医生没录入却被 AI 填出内容的照抄类字段回退为占位符。

    Args:
        result: LLM 返回的字段字典（就地修改）
        req:    生成请求对象，医生录入的原始字段从这里取

    Returns:
        被回退的字段名列表，供调用方写日志。
    """
    reverted: list[str] = []
    if not isinstance(result, dict):
        return reverted
    for out_field, src_field in COPY_THROUGH_FIELDS.items():
        out_val = result.get(out_field)
        if _is_blank(out_val):
            continue
        if _is_blank(getattr(req, src_field, None)):
            result[out_field] = PLACEHOLDER
            reverted.append(out_field)
    return reverted
