"""
完整性质控规则引擎
基于规则配置检查病历必填项和基础要求
"""

COMPLETENESS_RULES = [
    {
        "rule_code": "CC001",
        "field": "chief_complaint",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "主诉未填写",
        "suggestion": "请填写患者主诉，格式：症状+持续时间，如“发热3天”",
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
    },
    {
        "rule_code": "CC003",
        "field": "history_present_illness",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "现病史未填写",
        "suggestion": "请详细描述现病史，包括发病时间、主要症状、病情演变等",
    },
    {
        "rule_code": "CC004",
        "field": "history_present_illness",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "too_short",
        "min_length": 20,
        "issue_description": "现病史内容过于简短，可能缺少关键信息",
        "suggestion": "现病史应包含：发病时间、诱因、主要症状、伴随症状、诊治经过",
    },
    {
        "rule_code": "CC005",
        "field": "past_history",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "empty",
        "issue_description": "既往史未填写",
        "suggestion": "请填写既往史，如无特殊病史请填写“否认高血压、糖尿病、冠心病等慢性病史”",
    },
    {
        "rule_code": "CC006",
        "field": "allergy_history",
        "issue_type": "completeness",
        "risk_level": "high",
        "check": "empty",
        "issue_description": "过敏史未填写",
        "suggestion": "过敏史为必填项，如无过敏请填写“否认药物及食物过敏史”",
    },
    {
        "rule_code": "CC007",
        "field": "physical_exam",
        "issue_type": "completeness",
        "risk_level": "medium",
        "check": "empty",
        "issue_description": "体格检查未填写",
        "suggestion": "请填写体格检查结果，至少包含生命体征（T/P/R/BP）",
    },
]


def check_completeness(content: dict) -> list[dict]:
    issues = []
    for rule in COMPLETENESS_RULES:
        field = rule["field"]
        value = content.get(field, "")
        triggered = False

        if rule["check"] == "empty" and not value:
            triggered = True
        elif rule["check"] == "too_long" and value and len(value) > rule.get("max_length", 9999):
            triggered = True
        elif rule["check"] == "too_short" and value and len(value) < rule.get("min_length", 0):
            triggered = True

        if triggered:
            issues.append({
                "issue_type": rule["issue_type"],
                "risk_level": rule["risk_level"],
                "field_name": field,
                "issue_description": rule["issue_description"],
                "suggestion": rule["suggestion"],
            })
    return issues
