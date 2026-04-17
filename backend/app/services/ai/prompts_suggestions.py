"""
AI 建议 Prompt 库（app/services/ai/prompts_suggestions.py）

包含临床辅助建议类的 prompt 模板：
  INQUIRY_SUGGESTIONS_PROMPT  : 追问建议——按病情类型生成 4-6 条结构化追问问题，
                                每条含优先级/危险信号/选项类型（single/multi），
                                严禁重复问已知信息
  EXAM_SUGGESTIONS_PROMPT     : 检查建议——根据症状推荐本院现有设备的检查项目（3-6条），
                                严格限制在院内设备列表范围内，不推荐院外检查
  DIAGNOSIS_SUGGESTION_PROMPT : 诊断建议——结合问诊信息和追问结果，给出 3-5 个
                                可能诊断，按可信度排序，每条含依据和下一步建议

调用来源：
  INQUIRY_SUGGESTIONS_PROMPT  → ai_suggestions.py 路由的 /inquiry-suggestions 接口
  EXAM_SUGGESTIONS_PROMPT     → ai_suggestions.py 路由的 /exam-suggestions 接口
  DIAGNOSIS_SUGGESTION_PROMPT → ai_suggestions.py 路由的 /diagnosis-suggestions 接口
"""

INQUIRY_SUGGESTIONS_PROMPT = """你是一名临床医生，请严格按照以下步骤为患者生成追问问题，必须输出完整JSON。

患者信息：
主诉：{chief_complaint}
现病史：{history}
诊断：{initial_impression}

第一步：分析已知信息（在 known_info 字段中列出）
第二步：判断病情类型（在 condition_type 字段中填写）
第三步：根据病情类型生成专项追问（在 suggestions 中输出，严禁重复已知信息）

病情类型与对应追问方向（必须按此执行）：
- 皮肤外伤（擦伤/裂伤/挫伤）→ 受伤经过、伤口污染程度、有无异物、破伤风接种史、有无皮肤过敏/糖尿病影响愈合
- 骨关节外伤（骨折/扭伤/脱位）→ 受伤机制、能否负重行走、有无麻木感、末梢血运情况、X线是否已拍
- 内科急症（胸痛/腹痛/头痛等）→ 起病时间地点、疼痛性质、加重缓解因素、伴随症状、既往类似发作
- 感染（发热/炎症）→ 体温峰值、热型、感染接触史、近期用药、疫苗接种情况
- 慢性病急性加重 → 基础疾病控制情况、近期用药规律性、急性诱因

输出格式（必须完整填写所有字段）：
{{
  "known_info": ["已知信息1（如：部位=腿部外侧）", "已知信息2（如：类型=擦伤）"],
  "condition_type": "病情类型（如：皮肤外伤-擦伤）",
  "suggestions": [
    {{
      "text": "问题（简洁，不超过20字）",
      "priority": "high/medium/low",
      "is_red_flag": true/false,
      "category": "受伤机制/伤口情况/危险信号/功能评估/既往信息",
      "option_type": "single或multi",
      "options": ["选项1", "选项2", "选项3"]
    }}
  ]
}}

option_type判断规则（必须逐题判断，不能统一填同一个值）：
- single：该题的选项之间逻辑上互斥，患者只能属于其中一种情况（如评分区间、程度分级、单一原因、时间节点等）
- multi：该题的选项可以同时成立，患者可能符合多个（如伴随症状、过敏药物、慢性病史等）
- 判断依据是选项语义，而非题目类型；如疼痛评分区间→single，伴随症状→multi

硬性规则：
- known_info 中列出的内容，绝对不能出现在 suggestions 的问题里
- suggestions 必须4-6条，每条 options 必须2-4个，与该病情直接相关
- 禁止出现"您的主要症状是什么""症状持续多久了"这类对已明确诊断的患者毫无意义的通用问题
- options中禁止出现"有"/"无"、"是"/"否"、"正常"/"异常"等互斥对立选项；选项均为正向具体描述，患者不勾选即代表阴性"""

EXAM_SUGGESTIONS_PROMPT = """你是临床检查建议助手。根据患者信息，提供合理的辅助检查建议。

主诉：{chief_complaint}
现病史：{history_present_illness}
初步印象：{initial_impression}
科室：{department}

【重要限制】本院现有检查设备如下，只能从以下范围内推荐，不得推荐不在列表中的检查：
影像类：CT、核磁（MRI）、DR（数字X光）、B超（超声）、骨密度仪
心电类：心电图、动态心电图（Holter）、动态血压监测
内镜类：胃镜、肠镜
呼气试验：碳14呼气试验（幽门螺杆菌检测）
化验类：血常规、尿常规、便常规、肝功能、肾功能、血糖、血脂、电解质、凝血功能、甲状腺功能、肿瘤标志物、感染指标（CRP/PCT/ESR）、心肌酶、BNP、D-二聚体、血型、传染病筛查及其他常规化验

请输出JSON格式，3-6条建议：
{{
  "suggestions": [
    {{
      "exam_name": "检查名称（必须在上述范围内）",
      "category": "basic",
      "reason": "推荐理由（结合患者具体症状说明）"
    }}
  ]
}}

category说明：basic（基础必查）/ differential（鉴别诊断）/ high_risk（高风险补充）
要求：仅做建议，不替代医生决策，不编造未提及的信息，严格只推荐本院现有设备能完成的检查。"""

DIAGNOSIS_SUGGESTION_PROMPT = """你是一名经验丰富的临床医生助手。根据以下问诊信息和追问结果，给出3-5个可能的初步诊断建议。

主诉：{chief_complaint}
现病史：{history}
已有初步印象：{initial_impression}

追问记录：
{inquiry_answers}

请输出JSON格式：
{{
  "diagnoses": [
    {{
      "name": "诊断名称（规范医学术语）",
      "confidence": "high/medium/low",
      "reasoning": "简要说明依据（1-2句话）",
      "next_steps": "建议下一步（检查或处理）"
    }}
  ]
}}

要求：
- confidence=high 表示高度符合当前症状
- 诊断名称使用规范中文医学术语
- 按可能性从高到低排列
- 不要编造未提及的症状或病史"""
