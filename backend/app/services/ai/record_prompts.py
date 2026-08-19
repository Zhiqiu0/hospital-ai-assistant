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

from typing import Any

from app.services.ai.ai_utils import compose_physical_exam
from app.services.ai.record_prompts_inpatient import (
    INPATIENT_TITLES,
    build_inpatient_prompt,
)
from app.services.ai.record_prompts_shared import (
    TRUTHFULNESS_RULES,
    format_schema_block,
)
from app.services.ai.record_schemas import (
    EMERGENCY_SCHEMA,
    OUTPATIENT_SCHEMA,
    PLACEHOLDER,
    coalesce_field,
    sanitize_inline_field,
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
        # 身份字段走 sanitize_inline_field：压平换行 + 截断超长，防 prompt 注入
        # （患者姓名等是外部可控输入，换行可伪造新的 prompt 段落）2026-06-11
        f"姓名：{sanitize_inline_field(getattr(req, 'patient_name', None), '患者')}  "
        f"性别：{sanitize_inline_field(getattr(req, 'patient_gender', None), '未知')}  "
        f"年龄：{sanitize_inline_field(getattr(req, 'patient_age', None), '未知')}",
        f"主诉：{coalesce_field(getattr(req, 'chief_complaint', None))}",
        f"现病史：{coalesce_field(getattr(req, 'history_present_illness', None))}",
        f"既往史：{coalesce_field(getattr(req, 'past_history', None))}",
        f"过敏史：{coalesce_field(getattr(req, 'allergy_history', None))}",
        f"个人史：{coalesce_field(getattr(req, 'personal_history', None))}",
        f"家族史：{coalesce_field(getattr(req, 'family_history', None))}",
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


# ─── 门诊书写风格约束（2026-08-19 对照濮氏门诊病历补，与住院 INPATIENT_STYLE_RULES 同理） ───
#
# 用医院真实门诊病历跑生成链路发现：医生口语速记会原样落进病历（"精神还行/
# 家里没遗传病"），既往史甚至被压缩成一个"否认"（丢信息比口语更糟）。
# 与 TRUTHFULNESS_RULES 的边界：本块只管"怎么写"，事实增删仍由真实性规则禁止。
OUTPATIENT_STYLE_RULES = """━━━ 门诊病历书写风格（与上方真实性约束同时遵守） ━━━
1. 现病史/既往史/个人史/家族史/望诊/闻诊/其余阳性体征/复诊建议/注意事项等叙述性字段：
   把医生的口语速记整理成规范医学书面语，例如
   "撞到左胸"→"撞伤左侧胸部"、"有点肿"→"局部轻度肿胀"、"精神还行"→"精神尚可"、
   "家里没遗传病没传染病"→"否认家族遗传性疾病及传染病史"、"不舒服随时来"→"不适随诊"。
   只换表述、补全句式，**不得增加医生未提及的症状体征否认项，也不得删减医生提供的信息**
   （如医生说"身体一般，没做过手术没输过血"，应写"既往体质一般，否认手术史、输血史"，
   而不是压缩成"否认"）。
2. 主诉/诊断/舌象/脉象/治则治法/处理意见（药名剂量用法）仍严格照抄，不改写。"""


# ─── Prompt 构造入口 ────────────────────────────────────────────────


def build_outpatient_prompt(req: Any) -> str:
    """构造门诊（中医）的 JSON 输出 prompt。"""
    visit_nature = "初诊" if getattr(req, "is_first_visit", True) else "复诊"
    schema_block = format_schema_block(OUTPATIENT_SCHEMA)
    request_block = _build_request_block(req, include_tcm=True)
    return f"""你是一名专业的临床病历书写助手。请根据以下问诊信息，按照《浙江省中医门、急诊病历评分标准》生成规范的中医{visit_nature}病历**结构化数据**。

医生录入的原始信息：
{request_block}

请只输出 JSON 对象，key 严格匹配下列字段（不增不减），value 全为字符串：
{schema_block}

{TRUTHFULNESS_RULES}

{OUTPATIENT_STYLE_RULES}"""


def build_emergency_prompt(req: Any) -> str:
    """构造急诊的 JSON 输出 prompt。"""
    schema_block = format_schema_block(EMERGENCY_SCHEMA)
    request_block = _build_request_block(req, include_tcm=False)
    return f"""你是一名专业的急诊病历书写助手。请根据以下问诊信息，按照《急诊病历书写规范》生成规范的急诊病历**结构化数据**。

医生录入的原始信息：
{request_block}

请只输出 JSON 对象，key 严格匹配下列字段（不增不减），value 全为字符串：
{schema_block}

{TRUTHFULNESS_RULES}

急诊补充约束：
- 体格检查不需要中医四诊（不要输出 tcm_inspection / tongue_coating 等字段）
- 患者去向只能从五选一：回家观察 / 留院观察 / 收入住院 / 转院 / 手术室
- 仅当患者去向="留院观察"时填 observation_notes，其他场景留空字符串"""


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
    if record_type in INPATIENT_TITLES:
        return build_inpatient_prompt(record_type, req)
    raise ValueError(
        f"record_type={record_type!r} 尚未接入 JSON 模式（应通过 NEW_ARCH_RECORD_TYPES 白名单过滤）"
    )


# ─── 润色 prompt（同构 JSON 路线，复用上面 build_record_prompt 当底） ──
#
# 注：补全 prompt 已于 2026-05-24 下线 —— 旧 build_supplement_prompt 让 LLM
# 重写完整 JSON 后由 renderer 整段重画，会把医生现场修改物理覆盖掉
# （bug：78 分逐条补全后整体补全回到 70）。新方案见
# services/ai/supplement_batch_service.py：一次 LLM 调用返回 N 个 {field, value}，
# 前端按 FIELD_TO_LINE_PREFIX 行级写入，与"逐条修复"同一机制。


# 润色场景的额外约束块
_POLISH_EXTRA_RULES = """━━━ 润色场景额外约束（覆盖上方规则；严格遵守） ━━━
1. 仍然只输出 schema 定义的 JSON 字段（key 不增不减，value 必须是字符串）
2. 只做三件事：① 口语化表述改为标准医学书面语；② 合并重复语句；③ 修正错别字/标点
3. 严禁修改任何客观数值（体温/血压/化验值等）、诊断名称、药物名称、医生录入原文
4. 严禁新增任何在草稿中找不到依据的诊断、症状、检查结果
5. 草稿中某字段若已规范，可原样照搬"""


def build_polish_prompt(record_type: str, req: Any) -> str:
    """润色 prompt = 生成 prompt 基础 + 现有草稿 + 润色约束。

    与补全的区别：不接受 qc_issues，专注语言规范化，禁止改动客观数据。
    """
    base = build_record_prompt(record_type, req)
    current = (getattr(req, "current_content", None) or "").strip() or "（草稿为空，无法润色）"
    return f"""{base}

━━━ 待润色的病历草稿 ━━━
{current}

{_POLISH_EXTRA_RULES}"""
