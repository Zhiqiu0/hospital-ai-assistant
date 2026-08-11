"""
病历操作 Prompt 库（app/services/ai/prompts_operations.py）

L3 治本路线后：润色 / 补全已迁移到 services/ai/record_prompts.py（JSON 模式）+
record_gen_v2_service.py（统一管线）。本文件仅保留续写 CONTINUE_PROMPT，
它仍是"自由文本输出 + 追加到末尾"语义，不需要 JSON schema 强约束。

包含：
  CONTINUE_PROMPT   : 续写病历——根据问诊信息补全已有病历的缺失部分，遵守性别约束

使用场景：
  CONTINUE_PROMPT   → ai_generation.py 路由的 /continue 接口
"""

CONTINUE_PROMPT = """你是临床病历书写助手。医生已经写了部分病历，请根据问诊信息续写未完成的部分。

患者信息：姓名：{patient_name}  性别：{patient_gender}  年龄：{patient_age}
病历类型：{record_type}

【性别约束—必须严格遵守】
- 若患者性别为男性（male/男），严禁出现月经史、末次月经、生育史、妇科等女性特有内容
- 若患者性别为女性（female/女），月经史/生育史为必填项
- 若性别未知，不得编造任何性别特异性内容

问诊信息：
主诉：{chief_complaint}
现病史：{history_present_illness}
既往史：{past_history}
过敏史：{allergy_history}
个人史：{personal_history}
体格检查：{physical_exam}
初步印象：{initial_impression}

已有病历内容：
{current_content}

请分析已有内容，找出缺失的部分，只输出需要补充的内容（不要重复已有内容）。
输出格式：直接输出补充的病历段落，格式与已有内容保持一致。
禁止编造未提及的症状或信息。"""


def build_continue_prompt(req, record_type_label: str, composed_physical_exam: str) -> str:
    """组装病历续写 prompt（从 api/v1/ai_generation.py 拆入，2026-08-11）。

    Args:
        req:                    ContinueRequest（字段可缺省，缺省填"未提供"）
        record_type_label:      病历类型中文名（如"门诊病历"）
        composed_physical_exam: 已合并生命体征的体格检查文本
    """
    return CONTINUE_PROMPT.format(
        record_type=record_type_label,
        patient_name=req.patient_name or "未知",
        patient_gender=req.patient_gender or "未知",
        patient_age=req.patient_age or "未知",
        chief_complaint=req.chief_complaint or "未提供",
        history_present_illness=req.history_present_illness or "未提供",
        past_history=req.past_history or "未提供",
        allergy_history=req.allergy_history or "未提供",
        personal_history=req.personal_history or "未提供",
        physical_exam=composed_physical_exam or "未提供",
        initial_impression=req.initial_impression or "未提供",
        current_content=req.current_content or "（暂无内容）",
    )
