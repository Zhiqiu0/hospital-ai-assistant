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
        "keywords": ["T:", "P:", "R:", "BP:"],
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
    # -- 辅助检查（仅住院病历）
    {
        "rule_code": "CC018",
        "field": "auxiliary_exam",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "empty_inpatient",
        "issue_description": "辅助检查（入院前）未填写——住院病历应记录入院前相关检查（扣0.5分）",
        "suggestion": "请填写入院前辅助检查结果；如无则填写「入院前未行相关辅助检查」",
        "score_impact": "-0.5分",
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


def check_completeness(content: dict, is_inpatient: bool = False) -> list:
    """
    检查病历完整性。
    is_inpatient=True 时对住院特有字段（婚育史、家族史、专项评估等）也进行检查。
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
        elif rule["check"] == "missing_keyword" and value:
            keywords = rule.get("keywords", [])
            require_any = rule.get("require_any", False)
            if require_any:
                triggered = not any(kw in value for kw in keywords)
            else:
                triggered = not all(kw in value for kw in keywords)

        if triggered:
            issues.append({
                "issue_type": rule["issue_type"],
                "risk_level": rule["risk_level"],
                "field_name": field,
                "issue_description": rule["issue_description"],
                "suggestion": rule["suggestion"],
                "score_impact": rule.get("score_impact", ""),
            })
    return issues
