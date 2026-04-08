# -*- coding: utf-8 -*-
"""
完整性质控规则引擎
基于规则配置检查病历必填项和基础要求
依据：《浙江省住院病历质量检查评分表（2021版）》
"""

COMPLETENESS_RULES = [
    # -- 主诉（2分）
    {
        "rule_code": "CC001",
        "field": "chief_complaint",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "主诉未填写（扣1分）",
        "suggestion": "请填写患者主诉，格式：症状+持续时间，如「发现左手拇指近节指腹包块2月余」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC002",
        "field": "chief_complaint",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "too_long",
        "max_length": 100,
        "issue_description": "主诉内容过长（超过100字），建议简洁描述",
        "suggestion": "主诉应简洁，建议控制在20-50字，详细内容放入现病史",
        "score_impact": "-0.5分",
    },
    # -- 现病史（6分）
    {
        "rule_code": "CC003",
        "field": "history_present_illness",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "现病史未填写（扣2分）",
        "suggestion": "请详细描述现病史，包括：发病时间/地点/起病缓急、主要症状特点及演变、诊治经过、一般情况（饮食/精神/睡眠/大小便）",
        "score_impact": "-2分",
    },
    {
        "rule_code": "CC004",
        "field": "history_present_illness",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "too_short",
        "min_length": 50,
        "issue_description": "现病史内容过于简短，可能缺少关键信息（扣0.5分）",
        "suggestion": "现病史应包含：①发病时间/地点/起病缓急 ②主要症状部位/性质/程度/演变/伴随症状 ③诊治经过及效果 ④一般情况（饮食/精神/睡眠/大小便）",
        "score_impact": "-0.5分",
    },
    # -- 既往史（2分）
    {
        "rule_code": "CC005",
        "field": "past_history",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "empty",
        "issue_description": "既往史未填写（扣0.5分）",
        "suggestion": "请填写既往史，如无特殊病史请填写「既往体质可，否认高血压、糖尿病、冠心病等慢性病史」",
        "score_impact": "-0.5分",
    },
    # -- 过敏史（缺失扣2分）
    {
        "rule_code": "CC006",
        "field": "allergy_history",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "过敏史未填写——此项缺失直接扣2分（高风险）",
        "suggestion": "过敏史为必填项，如无过敏请填写「否认药物及食物过敏史」",
        "score_impact": "-2分",
    },
    # -- 体格检查（2分）
    {
        "rule_code": "CC007",
        "field": "physical_exam",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "体格检查未填写（扣1分）",
        "suggestion": "请填写体格检查结果，至少包含生命体征（T/P/R/BP）及各系统检查",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC008",
        "field": "physical_exam",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "missing_keyword",
        "keywords": ["T:", "T ", "体温", "P:", "P ", "脉搏", "R:", "R ", "呼吸", "BP:", "BP ", "血压"],
        "require_any": True,
        "issue_description": "体格检查缺少生命体征记录（T/P/R/BP）（扣0.5分）",
        "suggestion": "请在体格检查中补充生命体征：T:__度 P:__次/分 R:__次/分 BP:__/__mmHg",
        "score_impact": "-0.5分",
    },
    # -- 婚育史（3分中的1分，仅住院病历）
    {
        "rule_code": "CC009",
        "field": "marital_history",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "婚育史未填写——住院病历必填项（扣1分）",
        "suggestion": "请填写婚育史，如「25岁结婚，配偶体健，育有1子1女，均体健」或「未婚」",
        "score_impact": "-1分",
    },
    # -- 家族史（3分中的1分，仅住院病历）
    {
        "rule_code": "CC010",
        "field": "family_history",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "家族史未填写——住院病历必填项（扣1分）",
        "suggestion": "请填写家族史，如「父母均健在，有1姐体健，否认家族性遗传病、传染病史，否认肿瘤家族史」",
        "score_impact": "-1分",
    },
    # -- 专项评估7项（缺1项扣1分，仅住院病历）
    {
        "rule_code": "CC011",
        "field": "pain_assessment",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "专项评估缺少：疼痛评估（NRS评分）——缺1项扣1分",
        "suggestion": "请填写疼痛NRS评分（0-10分），如「NRS评分0分，无明显疼痛」或「NRS评分3分，轻度疼痛」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC012",
        "field": "vte_risk",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "专项评估缺少：VTE（静脉血栓栓塞）风险评估——缺1项扣1分",
        "suggestion": "请填写VTE风险评估，如「VTE风险评估：低风险」或「中风险」或「高风险」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC013",
        "field": "nutrition_assessment",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "专项评估缺少：营养风险评估——缺1项扣1分",
        "suggestion": "请填写营养评估，如「营养状态良好，无营养风险」或「NRS2002评分：__分」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC014",
        "field": "psychology_assessment",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "专项评估缺少：心理状态评估——缺1项扣1分",
        "suggestion": "请填写心理评估，如「心理状态良好，无焦虑抑郁」或「PHQ评分：__分」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC015",
        "field": "rehabilitation_assessment",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "专项评估缺少：康复需求评估——缺1项扣1分",
        "suggestion": "请填写康复评估，如「无康复治疗需求」或「需要物理康复治疗」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC016",
        "field": "current_medications",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "专项评估缺少：当前用药评估——缺1项扣1分",
        "suggestion": "请填写当前用药情况，如「否认长期用药史」或「长期服用降压药（xx药 xmg qd）」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC017",
        "field": "religion_belief",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "empty_inpatient",
        "issue_description": "专项评估缺少：宗教信仰/饮食禁忌评估——缺1项扣1分",
        "suggestion": "请填写宗教信仰或饮食禁忌，如「无宗教信仰，无饮食禁忌」",
        "score_impact": "-1分",
    },
    # -- 病发时间（门诊+住院均必填）
    {
        "rule_code": "CC020",
        "field": "onset_time",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "病发时间未填写——病历必须记录发病时间（扣1分）",
        "suggestion": "请填写病发时间，格式：YYYY-MM-DD HH:mm（24小时制阿拉伯数字）",
        "score_impact": "-1分",
    },
    # -- 辅助检查（门诊+住院均必填）
    {
        "rule_code": "CC018",
        "field": "auxiliary_exam",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "辅助检查未填写——门诊病历必须记录辅助检查结果，如无检查请填写「暂无」（扣1分）",
        "suggestion": "请填写辅助检查结果；如未行相关检查请填写「暂无」，不可留空",
        "score_impact": "-1分",
    },
    # -- 入院诊断（仅住院病历）
    {
        "rule_code": "CC019",
        "field": "admission_diagnosis",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty_inpatient",
        "issue_description": "入院诊断未填写（扣2分）",
        "suggestion": "请填写规范中文入院诊断，如「左拇指近节皮下肿物」，主要诊断放首位",
        "score_impact": "-2分",
    },
]


# ── 复诊强制规则 ─────────────────────────────────────────────
# 复诊病历必须记录治疗后症状改变情况
REVISIT_REQUIRED_RULES = [
    {
        "rule_code": "RV001",
        "field": "history_present_illness",
        "issue_type": "completeness",
        "risk_level": "high",
        "issue_description": "复诊病历未记录治疗后症状改变情况——复诊必须记录上次治疗后症状的好转、无变化或加重情况（扣2分）",
        "suggestion": "请在现病史中补充上次治疗后的症状变化，如「经上次治疗后头痛明显缓解，仍有轻度头晕」或「服药后症状无明显改善，仍有……」",
        "score_impact": "-2分",
    },
]

# 检测复诊症状变化记录的关键词
_REVISIT_SYMPTOM_CHANGE_KEYWORDS = [
    "治疗后", "服药后", "用药后", "针灸后", "推拿后",
    "好转", "改善", "缓解", "减轻", "消失", "加重", "无变化", "未见好转",
    "上次就诊", "上次治疗", "复诊", "经治疗",
    "症状变化", "症状改变", "病情变化",
]


# ── 中医强制规则 ─────────────────────────────────────────────
# 当病历含有中医诊断 / 中医治疗 / 中药 / 针灸等内容时，以下字段全部必填
TCM_REQUIRED_RULES = [
    {
        "rule_code": "TCM001",
        "field": "tongue_coating",
        "issue_type": "completeness",
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【舌象】未填写——中医病历必须记录舌质、舌苔（扣2分）",
        "suggestion": "请在中医四诊区填写舌象，格式如：舌淡红苔薄白；或：舌红苔黄腻。舌象是中医辨证的核心依据。",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM002",
        "field": "pulse_condition",
        "issue_type": "completeness",
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【脉象】未填写——中医病历必须记录脉象（扣2分）",
        "suggestion": "请在中医四诊区填写脉象，格式如：脉弦细；或：脉滑数。脉象是中医切诊的必录内容。",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM003",
        "field": "tcm_syndrome_diagnosis",
        "issue_type": "completeness",
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【中医证候诊断】未填写——中医病历必须有证候诊断（扣2分）",
        "suggestion": "请填写中医证候诊断，格式如：肝阳上亢证；或：痰热壅肺证。证候诊断是中医辨证论治的基础。",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM004",
        "field": "tcm_disease_diagnosis",
        "issue_type": "completeness",
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【中医疾病诊断】未填写——中医病历必须有疾病诊断（扣1分）",
        "suggestion": "请填写中医疾病诊断，格式如：眩晕病；或：胸痹；或：感冒。",
        "score_impact": "-1分",
    },
    {
        "rule_code": "TCM005",
        "field": "treatment_method",
        "issue_type": "completeness",
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【治则治法】未填写——中医病历必须注明治疗原则（扣1分）",
        "suggestion": "请填写治则治法，如：平肝潜阳、滋养肝肾；或：清热化痰、止咳平喘。治法必须与证候诊断对应。",
        "score_impact": "-1分",
    },
    {
        "rule_code": "TCM006",
        "field": "tcm_inspection",
        "issue_type": "completeness",
        "risk_level": "medium",
        "issue_description": "病历含中医治疗，但【望诊】未填写——中医四诊应完整记录（扣0.5分）",
        "suggestion": "请在中医四诊区填写望诊内容，如：神清气爽，面色略红，体形中等。",
        "score_impact": "-0.5分",
    },
    {
        "rule_code": "TCM007",
        "field": "tcm_auscultation",
        "issue_type": "completeness",
        "risk_level": "medium",
        "issue_description": "病历含中医治疗，但【闻诊】未填写——中医四诊应完整记录（扣0.5分）",
        "suggestion": "请在中医四诊区填写闻诊内容，如：语声清晰，无异常气味；或：呼吸急促，可闻及哮鸣音。",
        "score_impact": "-0.5分",
    },
]

# 中医治疗检测关键词（出现任意一个 → 判定为含中医治疗）
_TCM_TREATMENT_KEYWORDS = [
    "中医诊断", "证候诊断", "治则", "治法", "中药", "针灸", "推拿",
    "中医治疗", "辨证", "汤", "丸", "散", "膏", "饮", "方",
    "穴位", "艾灸", "拔罐", "刮痧",
]


def _has_tcm_treatment(content: dict, record_text: str = "") -> bool:
    """检测病历是否含有中医治疗相关内容。"""
    # 检查结构化字段
    tcm_fields = [
        "treatment_method", "tcm_disease_diagnosis", "tcm_syndrome_diagnosis",
        "tongue_coating", "pulse_condition", "tcm_inspection", "tcm_auscultation",
    ]
    if any(content.get(f, "").strip() for f in tcm_fields):
        return True
    # 检查生成的病历文本
    if record_text:
        return any(kw in record_text for kw in _TCM_TREATMENT_KEYWORDS)
    return False


def check_completeness(content: dict, is_inpatient: bool = False, record_text: str = "", is_first_visit: bool = True) -> list:
    """
    检查病历完整性。
    is_inpatient=True 时对住院特有字段（婚育史、家族史、专项评估等）也进行检查。
    record_text 为已生成的病历正文，用于中医治疗检测。
    """
    issues = []
    for rule in COMPLETENESS_RULES:
        field = rule["field"]
        value = content.get(field, "")

        # empty_inpatient 类型：仅住院病历检查
        if rule["check"] == "empty_inpatient":
            if not is_inpatient:
                continue
            if not value:
                issues.append({
                    "issue_type": rule["issue_type"],
                    "risk_level": rule["risk_level"],
                    "field_name": field,
                    "issue_description": rule["issue_description"],
                    "suggestion": rule["suggestion"],
                    "score_impact": rule.get("score_impact", ""),
                })
            continue

        triggered = False

        if rule["check"] == "empty" and not value:
            triggered = True
        elif rule["check"] == "too_long" and value and len(value) > rule.get("max_length", 9999):
            triggered = True
        elif rule["check"] == "too_short" and value and len(value) < rule.get("min_length", 0):
            triggered = True
        elif rule["check"] == "missing_keyword":
            keywords = rule.get("keywords", [])
            require_any = rule.get("require_any", False)
            # 同时在结构字段 + 病历正文中检索
            search_text = (value or "") + " " + record_text
            if require_any:
                triggered = not any(kw in search_text for kw in keywords)
            else:
                triggered = not all(kw in search_text for kw in keywords)

        if triggered:
            issues.append({
                "issue_type": rule["issue_type"],
                "risk_level": rule["risk_level"],
                "field_name": field,
                "issue_description": rule["issue_description"],
                "suggestion": rule["suggestion"],
                "score_impact": rule.get("score_impact", ""),
            })

    # ── 复诊强制检查：必须记录治疗后症状改变情况 ──────────────
    if not is_first_visit:
        hpi = content.get("history_present_illness", "").strip()
        # 检查结构字段 + 病历正文是否含症状变化描述
        combined_text = hpi + " " + record_text
        has_change_desc = any(kw in combined_text for kw in _REVISIT_SYMPTOM_CHANGE_KEYWORDS)
        if not has_change_desc:
            issues.append({
                "issue_type": REVISIT_REQUIRED_RULES[0]["issue_type"],
                "risk_level": REVISIT_REQUIRED_RULES[0]["risk_level"],
                "field_name": REVISIT_REQUIRED_RULES[0]["field"],
                "issue_description": REVISIT_REQUIRED_RULES[0]["issue_description"],
                "suggestion": REVISIT_REQUIRED_RULES[0]["suggestion"],
                "score_impact": REVISIT_REQUIRED_RULES[0]["score_impact"],
            })

    # ── 中医强制检查：仅当确认含中医治疗时执行 ──────────────
    if _has_tcm_treatment(content, record_text):
        existing_fields = {i["field_name"] for i in issues}
        for rule in TCM_REQUIRED_RULES:
            field = rule["field"]
            value = content.get(field, "").strip()
            # 同时检查病历正文中是否有对应内容
            in_record = False
            if record_text:
                if field == "tongue_coating":
                    in_record = any(kw in record_text for kw in ["舌象", "舌质", "舌苔", "舌淡", "舌红", "舌暗"])
                elif field == "pulse_condition":
                    in_record = any(kw in record_text for kw in ["脉象", "脉弦", "脉滑", "脉细", "脉数", "脉缓", "脉沉"])
                elif field == "tcm_syndrome_diagnosis":
                    import re as _re
                    # 匹配"证候诊断："标签，或"中医诊断：XXX — XXX证"格式中的证候部分
                    in_record = bool(
                        any(kw in record_text for kw in ["证候诊断：", "证候诊断:", "证型：", "证型:"])
                        or _re.search(r'中医诊断[：:][^\n]*[—\-–][^\n]*[^\s]{2,}证', record_text)
                    )
                elif field == "tcm_disease_diagnosis":
                    import re as _re
                    # 匹配"中医诊断："标签，或"中医诊断：XXX病"格式
                    in_record = bool(
                        any(kw in record_text for kw in ["中医诊断：", "中医诊断:", "疾病诊断：", "疾病诊断:"])
                    )
                elif field == "treatment_method":
                    in_record = any(kw in record_text for kw in ["治则", "治法", "治则治法"])
                elif field == "tcm_inspection":
                    in_record = any(kw in record_text for kw in ["望诊", "神色", "面色", "形态"])
                elif field == "tcm_auscultation":
                    in_record = any(kw in record_text for kw in ["闻诊", "语声", "呼吸音", "气味"])
            if not value and not in_record and field not in existing_fields:
                issues.append({
                    "issue_type": rule["issue_type"],
                    "risk_level": rule["risk_level"],
                    "field_name": field,
                    "issue_description": rule["issue_description"],
                    "suggestion": rule["suggestion"],
                    "score_impact": rule.get("score_impact", ""),
                })

    return issues
