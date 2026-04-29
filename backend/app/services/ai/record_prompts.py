"""
病历 JSON 生成 prompt 构造器（services/ai/record_prompts.py）

L3 治本路线：把 quick-generate 主路径从"自由文本"切到"结构化 JSON"。
LLM 只输出 JSON 字段值，由 record_renderer 按统一模板拼成展示文本，
行格式 100% 符合 QC 契约，永远消除"切诊：脉弦"这类格式偏差 bug。

入口：build_record_prompt(record_type, request) -> str
内部按 record_type 取 schema，组装：
  ① 患者基本信息    ② 医生录入的问诊数据    ③ JSON schema 字段说明
  ④ 共享真实性硬约束（禁止编造、空字段写 [未填写] 等）

仅服务于 record_type ∈ NEW_ARCH_RECORD_TYPES（阶段 2: 门诊+急诊；
阶段 3 扩展到住院 + 病程类）；其他类型仍走旧 PROMPT_MAP 文本路径。
"""
from __future__ import annotations

from typing import Any, Mapping

from app.services.ai.ai_utils import compose_physical_exam
from app.services.ai.record_schemas import (
    EMERGENCY_SCHEMA,
    OUTPATIENT_SCHEMA,
    PLACEHOLDER,
    coalesce_field,
    get_schema,
)

# L3 阶段 3 已全量接入：10 个 record_type 全部走 JSON 模式。
NEW_ARCH_RECORD_TYPES: frozenset[str] = frozenset({
    "outpatient",
    "emergency",
    "admission_note",
    "first_course_record",
    "course_record",
    "senior_round",
    "discharge_record",
    "pre_op_summary",
    "op_record",
    "post_op_record",
})


# ─── 共享真实性硬约束（嵌入每个 prompt 末尾） ──────────────────────
_TRUTHFULNESS_RULES = """⚠️ 内容真实性硬约束（违反就是医疗合规事故）：
1. 严格只使用医生录入的问诊信息，**禁止编造任何医生未提供的内容**
2. 任何字段为空时，对应 JSON value **必须**填字符串 "[未填写，需补充]"，
   不得按"规范模板"自动补"发育正常""营养良好""无心脑血管疾病"等
3. 主诉/诊断/舌象/脉象/治则治法 这五项**严格照抄**医生录入原文，不得推断
4. 体格检查的生命体征（physical_exam_vitals）必须按
   "T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg" 一整行格式输出，
   严格照抄医生录入的体征数据；缺项写"[未测]"；全部为空写"[未填写，需补充]"
5. 输出**必须是合法 JSON**，key **严格匹配** schema 列出的字段（不增不减），
   value 全部为字符串类型；禁止任何前言、Markdown 装饰、代码块标记"""


def _format_schema_block(schema: Mapping[str, str]) -> str:
    """把 schema 字段表渲染成"- key: 描述"列表，注入 prompt 让 LLM 知道要填哪些 key。"""
    return "\n".join(f"- {key}: {desc}" for key, desc in schema.items())


def _build_request_block(req: Any, *, include_tcm: bool) -> str:
    """组装"医生录入"段落（患者信息 + 问诊数据），供 prompt 注入。

    用 getattr 容错：QuickGenerateRequest 的字段在不同 record_type 场景下
    可能未提供（如急诊不传中医四诊），缺字段视作占位符。
    """
    composed_physical_exam = compose_physical_exam(
        physical_exam=getattr(req, "physical_exam", "") or "",
        temperature=getattr(req, "temperature", "") or "",
        pulse=getattr(req, "pulse", "") or "",
        respiration=getattr(req, "respiration", "") or "",
        bp_systolic=getattr(req, "bp_systolic", "") or "",
        bp_diastolic=getattr(req, "bp_diastolic", "") or "",
        spo2=getattr(req, "spo2", "") or "",
        height=getattr(req, "height", "") or "",
        weight=getattr(req, "weight", "") or "",
    )
    lines: list[str] = [
        f"姓名：{coalesce_field(getattr(req, 'patient_name', None), '患者')}  "
        f"性别：{coalesce_field(getattr(req, 'patient_gender', None), '未知')}  "
        f"年龄：{coalesce_field(getattr(req, 'patient_age', None), '未知')}",
        f"主诉：{coalesce_field(getattr(req, 'chief_complaint', None))}",
        f"现病史：{coalesce_field(getattr(req, 'history_present_illness', None))}",
        f"既往史：{coalesce_field(getattr(req, 'past_history', None))}",
        f"过敏史：{coalesce_field(getattr(req, 'allergy_history', None))}",
        f"个人史：{coalesce_field(getattr(req, 'personal_history', None))}",
        f"体格检查（合并生命体征）：{composed_physical_exam or PLACEHOLDER}",
        f"辅助检查：{coalesce_field(getattr(req, 'auxiliary_exam', None))}",
    ]
    if include_tcm:
        lines.extend([
            f"中医望诊：{coalesce_field(getattr(req, 'tcm_inspection', None))}",
            f"中医闻诊：{coalesce_field(getattr(req, 'tcm_auscultation', None))}",
            f"舌象：{coalesce_field(getattr(req, 'tongue_coating', None))}",
            f"脉象：{coalesce_field(getattr(req, 'pulse_condition', None))}",
            f"西医诊断：{coalesce_field(getattr(req, 'western_diagnosis', None))}",
            f"中医疾病诊断：{coalesce_field(getattr(req, 'tcm_disease_diagnosis', None))}",
            f"中医证候诊断：{coalesce_field(getattr(req, 'tcm_syndrome_diagnosis', None))}",
            f"治则治法：{coalesce_field(getattr(req, 'treatment_method', None))}",
            f"处理意见：{coalesce_field(getattr(req, 'treatment_plan', None))}",
            f"复诊建议：{coalesce_field(getattr(req, 'followup_advice', None))}",
            f"注意事项：{coalesce_field(getattr(req, 'precautions', None))}",
        ])
    else:
        # 急诊：只有诊断 + 处置 + 留观 + 去向，无中医四诊
        # 留观记录可空（仅留院观察才填），故传 '' 兜底而非 PLACEHOLDER，
        # 让 LLM 看到"无要求"而不是"必须补"。
        lines.extend([
            f"诊断：{coalesce_field(getattr(req, 'initial_impression', None))}",
            f"急诊处置：{coalesce_field(getattr(req, 'treatment_plan', None))}",
            f"留观记录：{coalesce_field(getattr(req, 'observation_notes', None), '')}",
            f"患者去向：{coalesce_field(getattr(req, 'patient_disposition', None))}",
        ])
    return "\n".join(lines)


# ─── Prompt 构造入口 ────────────────────────────────────────────────


def build_outpatient_prompt(req: Any) -> str:
    """构造门诊（中医）的 JSON 输出 prompt。"""
    visit_nature = "初诊" if getattr(req, "is_first_visit", True) else "复诊"
    schema_block = _format_schema_block(OUTPATIENT_SCHEMA)
    request_block = _build_request_block(req, include_tcm=True)
    return f"""你是一名专业的临床病历书写助手。请根据以下问诊信息，按照《浙江省中医门、急诊病历评分标准》生成规范的中医{visit_nature}病历**结构化数据**。

医生录入的原始信息：
{request_block}

请只输出 JSON 对象，key 严格匹配下列字段（不增不减），value 全为字符串：
{schema_block}

{_TRUTHFULNESS_RULES}"""


def build_emergency_prompt(req: Any) -> str:
    """构造急诊的 JSON 输出 prompt。"""
    schema_block = _format_schema_block(EMERGENCY_SCHEMA)
    request_block = _build_request_block(req, include_tcm=False)
    return f"""你是一名专业的急诊病历书写助手。请根据以下问诊信息，按照《急诊病历书写规范》生成规范的急诊病历**结构化数据**。

医生录入的原始信息：
{request_block}

请只输出 JSON 对象，key 严格匹配下列字段（不增不减），value 全为字符串：
{schema_block}

{_TRUTHFULNESS_RULES}

急诊补充约束：
- 体格检查不需要中医四诊（不要输出 tcm_inspection / tongue_coating 等字段）
- 患者去向只能从五选一：回家观察 / 留院观察 / 收入住院 / 转院 / 手术室
- 仅当患者去向="留院观察"时填 observation_notes，其他场景留空字符串"""


# ─── 住院 + 病程类通用 prompt 构造 ──────────────────────────────────


def _build_inpatient_request_block(req: Any) -> str:
    """住院 / 病程类共用的"医生录入"段落。

    包含所有可能用到的字段，LLM 按 schema 字段表自行选用——
    多注入信息无害，少注入会让 LLM 编造（更危险）。
    """
    composed_physical_exam = compose_physical_exam(
        physical_exam=getattr(req, "physical_exam", "") or "",
        temperature=getattr(req, "temperature", "") or "",
        pulse=getattr(req, "pulse", "") or "",
        respiration=getattr(req, "respiration", "") or "",
        bp_systolic=getattr(req, "bp_systolic", "") or "",
        bp_diastolic=getattr(req, "bp_diastolic", "") or "",
        spo2=getattr(req, "spo2", "") or "",
        height=getattr(req, "height", "") or "",
        weight=getattr(req, "weight", "") or "",
    )
    return "\n".join([
        f"姓名：{coalesce_field(getattr(req, 'patient_name', None), '患者')}  "
        f"性别：{coalesce_field(getattr(req, 'patient_gender', None), '未知')}  "
        f"年龄：{coalesce_field(getattr(req, 'patient_age', None), '未知')}",
        f"主诉：{coalesce_field(getattr(req, 'chief_complaint', None))}",
        f"现病史：{coalesce_field(getattr(req, 'history_present_illness', None))}",
        f"既往史：{coalesce_field(getattr(req, 'past_history', None))}",
        f"过敏史/用药史：{coalesce_field(getattr(req, 'allergy_history', None))}",
        f"个人史：{coalesce_field(getattr(req, 'personal_history', None))}",
        f"婚育史：{coalesce_field(getattr(req, 'marital_history', None))}",
        f"月经史：{coalesce_field(getattr(req, 'menstrual_history', None))}",
        f"家族史：{coalesce_field(getattr(req, 'family_history', None))}",
        f"病史陈述者：{coalesce_field(getattr(req, 'history_informant', None))}",
        f"体格检查（含生命体征合并）：{composed_physical_exam or PLACEHOLDER}",
        f"辅助检查（入院前）：{coalesce_field(getattr(req, 'auxiliary_exam', None))}",
        f"入院诊断：{coalesce_field(getattr(req, 'initial_impression', None))}",
        f"专项评估｜当前用药：{coalesce_field(getattr(req, 'current_medications', None))}",
        f"专项评估｜疼痛评估（NRS）：{coalesce_field(getattr(req, 'pain_assessment', None))}",
        f"专项评估｜VTE风险：{coalesce_field(getattr(req, 'vte_risk', None))}",
        f"专项评估｜营养风险：{coalesce_field(getattr(req, 'nutrition_assessment', None))}",
        f"专项评估｜心理状态：{coalesce_field(getattr(req, 'psychology_assessment', None))}",
        f"专项评估｜康复需求：{coalesce_field(getattr(req, 'rehabilitation_assessment', None))}",
        f"专项评估｜宗教信仰/饮食禁忌：{coalesce_field(getattr(req, 'religion_belief', None))}",
    ])


# 病程类 prompt 标题映射（按 record_type 注入对应"你是 XXX 专家"开场白）
_INPATIENT_TITLES: dict[str, str] = {
    "admission_note": (
        "你是临床病历书写专家。请按照《浙江省住院病历质量检查评分表（2021版）》"
        "生成规范的入院记录**结构化数据**。"
    ),
    "first_course_record": (
        "你是临床病历书写专家。请生成规范的首次病程记录**结构化数据**。"
        "依据：首次病程记录须在入院 8 小时内完成。"
    ),
    "course_record": (
        "你是临床病历书写专家。请生成规范的日常病程记录**结构化数据**。"
        "依据：病情稳定至少每 3 天 1 次，病重 2 天 1 次，病危每天 1 次。"
    ),
    "senior_round": (
        "你是临床病历书写专家。请生成规范的上级医师查房记录**结构化数据**。"
        "依据：主治以上首查须 48 小时内完成；每周至少 2 次副高以上查房记录。"
    ),
    "discharge_record": (
        "你是临床病历书写专家。请生成规范的出院记录**结构化数据**。"
        "依据：出院记录须在出院后 24 小时内完成。"
    ),
    "pre_op_summary": (
        "你是临床病历书写专家。请生成规范的术前小结**结构化数据**。"
        "依据：术前小结须在手术前完成，经治医师书写，上级医师审签。"
    ),
    "op_record": (
        "你是临床病历书写专家。请生成规范的手术记录**结构化数据**。"
        "依据：手术记录须在手术后 24 小时内完成，由术者或第一助手书写。"
    ),
    "post_op_record": (
        "你是临床病历书写专家。请生成规范的术后病程记录**结构化数据**。"
        "依据：术后即刻记录须在麻醉清醒/返回病房后立即完成。"
    ),
}


def _build_inpatient_prompt(record_type: str, req: Any) -> str:
    """住院 + 7 个病程类共用 prompt 模板。"""
    title = _INPATIENT_TITLES[record_type]
    schema_block = _format_schema_block(get_schema(record_type))
    request_block = _build_inpatient_request_block(req)
    return f"""{title}

医生录入的原始信息：
{request_block}

请只输出 JSON 对象，key 严格匹配下列字段（不增不减），value 全为字符串：
{schema_block}

{_TRUTHFULNESS_RULES}"""


# ─── 公共入口 ────────────────────────────────────────────────────────


def build_record_prompt(record_type: str, req: Any) -> str:
    """按 record_type 分发到对应 prompt 构造器。

    Raises:
        ValueError: record_type 不在 NEW_ARCH_RECORD_TYPES 内。
    """
    if record_type == "outpatient":
        return build_outpatient_prompt(req)
    if record_type == "emergency":
        return build_emergency_prompt(req)
    if record_type in _INPATIENT_TITLES:
        return _build_inpatient_prompt(record_type, req)
    raise ValueError(
        f"record_type={record_type!r} 尚未接入 JSON 模式（应通过 NEW_ARCH_RECORD_TYPES 白名单过滤）"
    )
