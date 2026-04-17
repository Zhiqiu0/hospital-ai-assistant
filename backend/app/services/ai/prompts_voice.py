"""
语音结构化 Prompt 库（app/services/ai/prompts_voice.py）

包含将语音转写文本结构化为问诊表单的 prompt 模板：
  VOICE_STRUCTURE_PROMPT_OUTPATIENT : 门诊语音结构化——含中医四诊字段
                                      （舌象/脉象/望诊/闻诊/证候诊断/治则治法）
  VOICE_STRUCTURE_PROMPT_INPATIENT  : 住院语音结构化——含专项评估七项
                                      （疼痛/VTE/营养/心理/康复/用药/宗教）

两个 prompt 均输出三部分内容：
  1. transcript_summary  : 对话概括（1-2句）
  2. speaker_dialogue    : 按 doctor/patient/uncertain 区分的逐句对话
  3. inquiry             : 结构化问诊字段（直接填入 InquiryInput 表单）
  4. draft_record        : 完整病历草稿文本（直接显示在编辑区）

调用来源：
  均由 ai_voice.py 路由的 /voice-records/{id}/structure 接口调用，
  根据 is_inpatient 参数选择对应模板。
"""

VOICE_STRUCTURE_PROMPT_OUTPATIENT = """你是一名临床门诊病历助手。请根据以下医患对话转写内容，提炼出结构化问诊信息，并生成一份逻辑清晰的门诊病历草稿。

患者信息：
姓名：{patient_name}
性别：{patient_gender}
年龄：{patient_age}

现有问诊信息（如有）：
{existing_inquiry}

对话转写：
{transcript}

请输出 JSON：
{{
  "transcript_summary": "对本次对话的简要概括，1-2句话",
  "speaker_dialogue": [
    {{"speaker": "doctor", "text": "医生说的话"}},
    {{"speaker": "patient", "text": "患者说的话"}},
    {{"speaker": "uncertain", "text": "无法确定归属的话"}}
  ],
  "inquiry": {{
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "physical_exam": "体格检查（一般体征）",
    "tcm_inspection": "望诊内容（神色形态）",
    "tcm_auscultation": "闻诊内容（声音气味）",
    "tongue_coating": "舌象（舌质+舌苔，如：舌淡红苔薄白）",
    "pulse_condition": "脉象（如：脉弦细）",
    "western_diagnosis": "西医诊断",
    "tcm_disease_diagnosis": "中医疾病诊断（如：眩晕病）",
    "tcm_syndrome_diagnosis": "中医证候诊断（如：肝阳上亢证）",
    "treatment_method": "治则治法（如：平肝潜阳）",
    "treatment_plan": "处理意见（用药/治疗方案）",
    "followup_advice": "复诊建议",
    "initial_impression": "初步印象（补充）"
  }},
  "draft_record": "按【主诉】【现病史】【既往史】【过敏史】【个人史】【体格检查（含中医四诊、舌象脉象）】【辅助检查】【诊断（中医诊断含疾病+证候，西医诊断）】【治疗意见及措施（治则治法、处理意见、复诊建议）】输出的中医门诊病历草稿"
}}

要求：
- 只基于对话内容提炼，不得虚构
- 医生提问与患者回答混杂时，优先抽取患者已明确表达的事实
- 尽量区分 doctor / patient / uncertain 三类说话人；无法确定时标 uncertain
- 字段没有提到就输出空字符串
- 语言要书面化、时间线清晰、适合直接进入门诊病历编辑"""

VOICE_STRUCTURE_PROMPT_INPATIENT = """你是一名住院病历助手。请根据以下医患对话转写内容，提炼结构化入院问诊信息，并生成一份逻辑清晰的入院记录草稿。

患者信息：
姓名：{patient_name}
性别：{patient_gender}
年龄：{patient_age}

现有问诊信息（如有）：
{existing_inquiry}

对话转写：
{transcript}

请输出 JSON：
{{
  "transcript_summary": "对本次对话的简要概括，1-2句话",
  "speaker_dialogue": [
    {{"speaker": "doctor", "text": "医生说的话"}},
    {{"speaker": "patient", "text": "患者说的话"}},
    {{"speaker": "uncertain", "text": "无法确定归属的话"}}
  ],
  "inquiry": {{
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "physical_exam": "体格检查",
    "initial_impression": "入院诊断或初步印象",
    "history_informant": "病史陈述者",
    "marital_history": "婚育史",
    "menstrual_history": "月经史",
    "family_history": "家族史",
    "current_medications": "当前用药",
    "rehabilitation_assessment": "康复需求评估",
    "religion_belief": "宗教信仰或饮食禁忌",
    "pain_assessment": "疼痛评分",
    "vte_risk": "VTE风险",
    "nutrition_assessment": "营养评估",
    "psychology_assessment": "心理评估",
    "auxiliary_exam": "辅助检查",
    "admission_diagnosis": "入院诊断"
  }},
  "draft_record": "按【主诉】【现病史】【既往史】【个人史】【婚育史】【月经史】【家族史】【专项评估】【体格检查】【辅助检查】【入院诊断】输出的入院记录草稿"
}}

要求：
- 只基于对话内容提炼，不得虚构
- 未提及字段输出空字符串
- 尽量区分 doctor / patient / uncertain 三类说话人；无法确定时标 uncertain
- 若未提及明确评分，不要编造数值
- 输出语言规范、条理清晰，适合住院病历整理"""
