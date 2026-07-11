"""
门诊 / 急诊 / 住院入院记录渲染器（services/ai/_render_visit.py）

record_renderer.py 拆分出的「接诊类」渲染器：outpatient / emergency /
admission_note。这三类都带请求层元数据（visit_time / onset_time /
patient_gender）且体格检查是多子行结构，与病程类差异较大，单独成模块。

依赖方向：本模块 → _render_common（只 import 底层 helper，不 import record_renderer）。
"""

from __future__ import annotations

from typing import Optional

from app.services.ai._render_common import (
    _merge_tcm_diagnosis,
    _section,
    _subline,
    _v,
)


# ─── 门诊（中医） ────────────────────────────────────────────────────


def render_outpatient(
    data: dict,
    *,
    visit_time: Optional[str] = None,
    onset_time: Optional[str] = None,
    **_extra,
) -> str:
    """渲染门诊病历文本。

    输入 data 里需要的字段见 record_schemas.OUTPATIENT_SCHEMA。
    visit_time / onset_time 是请求层元数据（非 LLM 输出），首行展示用。

    输出严格符合契约：
      - 【体格检查】首行是 'T:...' 生命体征
      - 中医四诊 4 行用 '望诊：' / '闻诊：' / '切诊·舌象：' / '切诊·脉象：' 子行
      - 【诊断】用 '中医诊断：X — Y' / '西医诊断：xxx' 子行
      - 【治疗意见及措施】用 '治则治法：' / '处理意见：' / '复诊建议：' / '注意事项：' 子行
    """
    parts: list[str] = []

    # 首行元数据（与原 prompt 契约一致）
    if visit_time or onset_time:
        parts.append(
            f"就诊时间：{visit_time or '未记录'}　病发时间：{onset_time or '未记录'}"
        )

    # 主诉/现病史/既往史/过敏史/个人史 — 章节级整段
    parts.append(_section("【主诉】", _v(data, "chief_complaint")))
    parts.append(_section("【现病史】", _v(data, "history_present_illness")))
    parts.append(_section("【既往史】", _v(data, "past_history")))
    parts.append(_section("【过敏史】", _v(data, "allergy_history")))
    parts.append(_section("【个人史】", _v(data, "personal_history")))

    # 体格检查 — 多行子结构
    pe_lines = [
        _v(data, "physical_exam_vitals"),  # 生命体征行（已是 'T:...' 格式）
        _subline("望诊：", _v(data, "tcm_inspection")),
        _subline("闻诊：", _v(data, "tcm_auscultation")),
        _subline("切诊·舌象：", _v(data, "tongue_coating")),
        _subline("切诊·脉象：", _v(data, "pulse_condition")),
        _subline("其余阳性体征：", _v(data, "physical_exam_text")),
    ]
    parts.append(_section("【体格检查】", "\n".join(pe_lines)))

    # 辅助检查 — 章节级，无内容写"暂无"（与 prompt 契约一致，不写占位符）
    aux = data.get("auxiliary_exam")
    aux_text = (str(aux).strip() if aux else "") or "暂无"
    parts.append(_section("【辅助检查】", aux_text))

    # 诊断 — 中医诊断合并行 + 西医诊断子行
    tcm_line = _merge_tcm_diagnosis(
        _v(data, "tcm_disease_diagnosis"),
        _v(data, "tcm_syndrome_diagnosis"),
    )
    diagnosis_lines = [
        _subline("中医诊断：", tcm_line),
        _subline("西医诊断：", _v(data, "western_diagnosis")),
    ]
    parts.append(_section("【诊断】", "\n".join(diagnosis_lines)))

    # 治疗意见及措施 — 4 个子行
    # 注意事项可空（prompt 里 conditional 注入），按现状只在有值时显示该行
    treatment_lines = [
        _subline("治则治法：", _v(data, "treatment_method")),
        _subline("处理意见：", _v(data, "treatment_plan")),
        _subline("复诊建议：", _v(data, "followup_advice")),
    ]
    precautions_val = data.get("precautions")
    if precautions_val and str(precautions_val).strip():
        treatment_lines.append(_subline("注意事项：", str(precautions_val).strip()))
    parts.append(_section("【治疗意见及措施】", "\n".join(treatment_lines)))

    return "\n\n".join(parts)


# ─── 急诊 ────────────────────────────────────────────────────────────


def render_emergency(
    data: dict,
    *,
    visit_time: Optional[str] = None,
    onset_time: Optional[str] = None,
    **_extra,
) -> str:
    """渲染急诊病历文本。

    输入字段见 record_schemas.EMERGENCY_SCHEMA。
    急诊不含中医四诊，体格检查段只有"T: 生命体征"+"重点体征"两行。

    输出严格符合契约：
      - 【体格检查】首行是 'T:...' 生命体征
      - 【急诊处置】/【患者去向】/（可选）【急诊留观记录】 都是独立章节
      - observation_notes 有值才渲染【急诊留观记录】章节，否则跳过
    """
    parts: list[str] = []

    if visit_time or onset_time:
        parts.append(
            f"就诊时间：{visit_time or '未记录'}　病发时间：{onset_time or '未记录'}"
        )

    parts.append(_section("【主诉】", _v(data, "chief_complaint")))
    parts.append(_section("【现病史】", _v(data, "history_present_illness")))
    parts.append(_section("【既往史】", _v(data, "past_history")))
    parts.append(_section("【过敏史】", _v(data, "allergy_history")))

    # 体格检查 — 生命体征行 + 重点体征行
    pe_lines = [
        _v(data, "physical_exam_vitals"),
        _subline("重点体征：", _v(data, "physical_exam_text")),
    ]
    parts.append(_section("【体格检查】", "\n".join(pe_lines)))

    # 辅助检查 — 空写"暂无"
    aux = data.get("auxiliary_exam")
    aux_text = (str(aux).strip() if aux else "") or "暂无"
    parts.append(_section("【辅助检查】", aux_text))

    parts.append(_section("【诊断】", _v(data, "diagnosis")))
    parts.append(_section("【急诊处置】", _v(data, "treatment_plan")))

    # 急诊留观记录 — 仅当 observation_notes 有值时才渲染该章节
    # 避免"回家观察"等无需留观的场景被 QC 误报
    obs = data.get("observation_notes")
    if obs and str(obs).strip():
        parts.append(_section("【急诊留观记录】", str(obs).strip()))

    parts.append(_section("【患者去向】", _v(data, "patient_disposition")))

    return "\n\n".join(parts)


# ─── 住院入院记录 ────────────────────────────────────────────────────


# 专项评估 7 子行的字段名 → 子行前缀（与 _SECTION_LINE_PREFIXES 一致）
_ASSESSMENT_LINES = [
    ("pain_assessment", "· 疼痛评估（NRS评分）："),
    ("vte_risk", "· VTE风险："),
    ("nutrition_assessment", "· 营养风险："),
    ("psychology_assessment", "· 心理状态："),
    ("rehabilitation_assessment", "· 康复需求："),
    ("current_medications", "· 当前用药："),
    ("religion_belief", "· 宗教信仰/饮食禁忌："),
]


def render_admission_note(
    data: dict,
    *,
    patient_gender: Optional[str] = None,
    **_extra,
) -> str:
    """渲染住院入院记录文本。

    含 11 个章节 + 专项评估 7 子行 + 体格检查"T:"生命体征行。
    月经史章节仅女性患者输出（与 prompt 契约一致）。
    """
    parts: list[str] = []
    parts.append(_section("【主诉】", _v(data, "chief_complaint")))
    parts.append(_section("【现病史】", _v(data, "history_present_illness")))
    parts.append(_section("【既往史】", _v(data, "past_history")))
    parts.append(_section("【个人史】", _v(data, "personal_history")))
    parts.append(_section("【婚育史】", _v(data, "marital_history")))

    # 月经史：仅女性患者输出（男性患者跳过）
    if (patient_gender or "").strip() in {"女", "female"}:
        parts.append(_section("【月经史】", _v(data, "menstrual_history")))

    parts.append(_section("【家族史】", _v(data, "family_history")))
    parts.append(_section("【病史陈述者】", _v(data, "history_informant")))

    # 专项评估 — 7 子行
    assessment_lines = [
        _subline(prefix, _v(data, key)) for key, prefix in _ASSESSMENT_LINES
    ]
    parts.append(_section("【专项评估】", "\n".join(assessment_lines)))

    # 体格检查 — 生命体征行 + 文字描述
    pe_lines = [
        _v(data, "physical_exam_vitals"),
        _v(data, "physical_exam_text"),
    ]
    parts.append(_section("【体格检查】", "\n".join(pe_lines)))

    parts.append(_section("【辅助检查（入院前）】", _v(data, "auxiliary_exam")))
    parts.append(_section("【入院诊断】", _v(data, "admission_diagnosis")))
    return "\n\n".join(parts)
