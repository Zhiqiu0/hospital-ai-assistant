"""住院 + 病程类病历 prompt 构造（services/ai/record_prompts_inpatient.py）

从 record_prompts.py 拆出（2026-08-11 超标文件拆分）：本文件承载住院系
9 个 record_type（入院记录 + 7 类病程 + 出院）的 prompt 组装；
门诊/急诊与公共入口仍在 record_prompts.py，经 INPATIENT_TITLES 分发到这里。
"""
from typing import Any

from app.services.ai.ai_utils import compose_physical_exam
from app.services.ai.record_prompts_shared import (
    TRUTHFULNESS_RULES,
    format_schema_block,
)
from app.services.ai.record_schemas import (
    PLACEHOLDER,
    coalesce_field,
    get_schema,
    sanitize_inline_field,
)


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
        # 身份字段防 prompt 注入清洗，同 _build_request_block（2026-06-11）
        f"姓名：{sanitize_inline_field(getattr(req, 'patient_name', None), '患者')}  "
        f"性别：{sanitize_inline_field(getattr(req, 'patient_gender', None), '未知')}  "
        f"年龄：{sanitize_inline_field(getattr(req, 'patient_age', None), '未知')}",
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
# record_prompts.build_record_prompt 也用它判断"是否住院系类型"
INPATIENT_TITLES: dict[str, str] = {
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


def build_inpatient_prompt(record_type: str, req: Any) -> str:
    """住院 + 7 个病程类共用 prompt 模板。"""
    title = INPATIENT_TITLES[record_type]
    schema_block = format_schema_block(get_schema(record_type))
    request_block = _build_inpatient_request_block(req)
    return f"""{title}

医生录入的原始信息：
{request_block}

请只输出 JSON 对象，key 严格匹配下列字段（不增不减），value 全为字符串：
{schema_block}

{TRUTHFULNESS_RULES}"""
