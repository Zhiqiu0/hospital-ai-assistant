# -*- coding: utf-8 -*-
"""
完整性质控规则引擎
基于病历文本内容检查，不依赖 inquiry 结构化字段。
依据：《浙江省住院病历质量检查评分表（2021版）》
"""

# 每条规则的 record_keywords：病历文本中出现任意一个关键词即视为"已填写"
COMPLETENESS_RULES = [
    # -- 主诉（2分）
    {
        "rule_code": "CC001",
        "field_name": "chief_complaint",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["【主诉】", "主诉：", "主诉:"],
        "issue_description": "主诉未填写（扣1分）",
        "suggestion": "请填写患者主诉，格式：症状+持续时间，如「发现左手拇指近节指腹包块2月余」",
        "score_impact": "-1分",
    },
    # -- 现病史（6分）
    {
        "rule_code": "CC003",
        "field_name": "history_present_illness",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["【现病史】", "现病史：", "现病史:"],
        "issue_description": "现病史未填写（扣2分）",
        "suggestion": "请详细描述现病史，包括：发病时间/地点/起病缓急、主要症状特点及演变、诊治经过、一般情况",
        "score_impact": "-2分",
    },
    # -- 既往史（2分）
    {
        "rule_code": "CC005",
        "field_name": "past_history",
        "issue_type": "completeness",
        "risk_level": "medium",
        "record_keywords": ["【既往史】", "既往史：", "既往史:"],
        "issue_description": "既往史未填写（扣0.5分）",
        "suggestion": "请填写既往史，如无特殊病史请填写「既往体质可，否认高血压、糖尿病、冠心病等慢性病史」",
        "score_impact": "-0.5分",
    },
    # -- 过敏史（缺失扣2分）
    {
        "rule_code": "CC006",
        "field_name": "allergy_history",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["【过敏史】", "过敏史：", "过敏史:", "过敏", "否认药物", "否认食物"],
        "issue_description": "过敏史未填写——此项缺失直接扣2分（高风险）",
        "suggestion": "过敏史为必填项，如无过敏请填写「否认药物及食物过敏史」",
        "score_impact": "-2分",
    },
    # -- 体格检查（2分）
    {
        "rule_code": "CC007",
        "field_name": "physical_exam",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["【体格检查】", "体格检查：", "体格检查:"],
        "issue_description": "体格检查未填写（扣1分）",
        "suggestion": "请填写体格检查结果，至少包含生命体征（T/P/R/BP）及各系统检查",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC008",
        "field_name": "physical_exam_vitals",
        "issue_type": "completeness",
        "risk_level": "medium",
        "record_keywords": ["T:", "T ", "体温", "P:", "P ", "脉搏", "R:", "R ", "呼吸", "BP:", "BP ", "血压"],
        "issue_description": "体格检查缺少生命体征记录（T/P/R/BP）（扣0.5分）",
        "suggestion": "请在体格检查中补充生命体征：T:__度 P:__次/分 R:__次/分 BP:__/__mmHg",
        "score_impact": "-0.5分",
    },
    # -- 辅助检查（门诊+住院均必填）
    {
        "rule_code": "CC018",
        "field_name": "auxiliary_exam",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["【辅助检查】", "辅助检查：", "辅助检查:", "暂无检查", "暂无"],
        "issue_description": "辅助检查未填写——病历必须记录辅助检查结果，如无检查请填写「暂无」（扣1分）",
        "suggestion": "请填写辅助检查结果；如未行相关检查请填写「暂无」，不可留空",
        "score_impact": "-1分",
    },
    # -- 病发时间（门诊+住院均必填）
    {
        "rule_code": "CC020",
        "field_name": "onset_time",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["病发时间", "发病时间", "起病时间", "onset"],
        "issue_description": "病发时间未填写——病历必须记录发病时间（扣1分）",
        "suggestion": "请填写病发时间，格式：YYYY-MM-DD HH:mm（24小时制阿拉伯数字）",
        "score_impact": "-1分",
    },
]

# 住院病历专用规则（is_inpatient=True 时才检查）
INPATIENT_RULES = [
    {
        "rule_code": "CC009",
        "field_name": "marital_history",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["【婚育史】", "婚育史：", "婚育史:", "未婚", "已婚", "离异", "丧偶"],
        "issue_description": "婚育史未填写——住院病历必填项（扣1分）",
        "suggestion": "请填写婚育史，如「25岁结婚，配偶体健，育有1子1女，均体健」或「未婚」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC010",
        "field_name": "family_history",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["【家族史】", "家族史：", "家族史:"],
        "issue_description": "家族史未填写——住院病历必填项（扣1分）",
        "suggestion": "请填写家族史，如「父母均健在，否认家族性遗传病、传染病史，否认肿瘤家族史」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC011",
        "field_name": "pain_assessment",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["NRS评分", "NRS:", "NRS：", "疼痛评分", "疼痛评估", "疼痛NRS"],
        "issue_description": "专项评估缺少：疼痛评估（NRS评分）——缺1项扣1分",
        "suggestion": "请填写疼痛NRS评分（0-10分），如「NRS评分0分，无明显疼痛」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC012",
        "field_name": "vte_risk",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["VTE", "静脉血栓", "血栓风险", "血栓栓塞"],
        "issue_description": "专项评估缺少：VTE（静脉血栓栓塞）风险评估——缺1项扣1分",
        "suggestion": "请填写VTE风险评估，如「VTE风险评估：低风险」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC013",
        "field_name": "nutrition_assessment",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["营养评估", "营养风险", "NRS2002", "营养状态"],
        "issue_description": "专项评估缺少：营养风险评估——缺1项扣1分",
        "suggestion": "请填写营养评估，如「营养状态良好，无营养风险」或「NRS2002评分：__分」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC014",
        "field_name": "psychology_assessment",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["心理评估", "心理状态", "PHQ", "焦虑", "抑郁评估"],
        "issue_description": "专项评估缺少：心理状态评估——缺1项扣1分",
        "suggestion": "请填写心理评估，如「心理状态良好，无焦虑抑郁」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC015",
        "field_name": "rehabilitation_assessment",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["康复评估", "康复需求", "康复治疗需求"],
        "issue_description": "专项评估缺少：康复需求评估——缺1项扣1分",
        "suggestion": "请填写康复评估，如「无康复治疗需求」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC016",
        "field_name": "current_medications",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["用药评估", "当前用药", "长期用药", "否认长期用药", "用药情况"],
        "issue_description": "专项评估缺少：当前用药评估——缺1项扣1分",
        "suggestion": "请填写当前用药情况，如「否认长期用药史」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC017",
        "field_name": "religion_belief",
        "issue_type": "completeness",
        "risk_level": "medium",
        "record_keywords": ["宗教", "饮食禁忌", "无宗教", "无饮食禁忌"],
        "issue_description": "专项评估缺少：宗教信仰/饮食禁忌评估——缺1项扣1分",
        "suggestion": "请填写宗教信仰或饮食禁忌，如「无宗教信仰，无饮食禁忌」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC019",
        "field_name": "admission_diagnosis",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["【入院诊断】", "入院诊断：", "入院诊断:"],
        "issue_description": "入院诊断未填写（扣2分）",
        "suggestion": "请填写规范中文入院诊断，如「左拇指近节皮下肿物」，主要诊断放首位",
        "score_impact": "-2分",
    },
]


# ── 复诊强制规则 ─────────────────────────────────────────────
_REVISIT_SYMPTOM_CHANGE_KEYWORDS = [
    "治疗后", "服药后", "用药后", "针灸后", "推拿后",
    "好转", "改善", "缓解", "减轻", "消失", "加重", "无变化", "未见好转",
    "上次就诊", "上次治疗", "复诊", "经治疗",
    "症状变化", "症状改变", "病情变化",
]

# ── 中医强制规则 ─────────────────────────────────────────────
TCM_REQUIRED_RULES = [
    {
        "rule_code": "TCM001",
        "field_name": "tongue_coating",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["舌象", "舌质", "舌苔", "舌淡", "舌红", "舌暗", "舌胖"],
        "issue_description": "病历含中医治疗，但【舌象】未填写——中医病历必须记录舌质、舌苔（扣2分）",
        "suggestion": "请填写舌象，格式如：舌淡红苔薄白；或：舌红苔黄腻。",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM002",
        "field_name": "pulse_condition",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["脉象", "脉弦", "脉滑", "脉细", "脉数", "脉缓", "脉沉", "脉浮"],
        "issue_description": "病历含中医治疗，但【脉象】未填写——中医病历必须记录脉象（扣2分）",
        "suggestion": "请填写脉象，格式如：脉弦细；或：脉滑数。",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM003",
        "field_name": "tcm_syndrome_diagnosis",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["证候诊断：", "证候诊断:", "证型：", "证型:", "辨证："],
        "record_pattern": r"[\u4e00-\u9fa5]{2,}证",  # 兼容任意格式的中医证型名称
        "issue_description": "病历含中医治疗，但【中医证候诊断】未填写（扣2分）",
        "suggestion": "请填写中医证候诊断，格式如：肝阳上亢证；或：痰热壅肺证。",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM004",
        "field_name": "tcm_disease_diagnosis",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["中医诊断：", "中医诊断:", "疾病诊断：", "疾病诊断:"],
        "issue_description": "病历含中医治疗，但【中医疾病诊断】未填写（扣1分）",
        "suggestion": "请填写中医疾病诊断，格式如：眩晕病；或：胸痹。",
        "score_impact": "-1分",
    },
    {
        "rule_code": "TCM005",
        "field_name": "treatment_method",
        "issue_type": "completeness",
        "risk_level": "high",
        "record_keywords": ["治则", "治法", "治则治法"],
        "issue_description": "病历含中医治疗，但【治则治法】未填写（扣1分）",
        "suggestion": "请填写治则治法，如：平肝潜阳、滋养肝肾。",
        "score_impact": "-1分",
    },
    {
        "rule_code": "TCM006",
        "field_name": "tcm_inspection",
        "issue_type": "completeness",
        "risk_level": "medium",
        "record_keywords": ["望诊", "神色", "面色", "神清", "形态"],
        "issue_description": "病历含中医治疗，但【望诊】未填写（扣0.5分）",
        "suggestion": "请填写望诊内容，如：神清气爽，面色略红，体形中等。",
        "score_impact": "-0.5分",
    },
    {
        "rule_code": "TCM007",
        "field_name": "tcm_auscultation",
        "issue_type": "completeness",
        "risk_level": "medium",
        "record_keywords": ["闻诊", "语声", "呼吸音", "气味"],
        "issue_description": "病历含中医治疗，但【闻诊】未填写（扣0.5分）",
        "suggestion": "请填写闻诊内容，如：语声清晰，无异常气味。",
        "score_impact": "-0.5分",
    },
]

_TCM_TREATMENT_KEYWORDS = [
    "中医诊断", "证候诊断", "治则", "治法", "中药", "针灸", "推拿",
    "中医治疗", "辨证", "中药汤剂", "中成药", "中药方", "中药饮片",
    "穴位", "艾灸", "拔罐", "刮痧", "草药",
]


def check_completeness(record_text: str, is_inpatient: bool = False, is_first_visit: bool = True) -> list:
    """
    规则引擎：只做结构性存在检查（有没有该章节/字段），不做语义内容检查。
    语义内容质量（如中医四诊是否规范、诊断是否准确）交给 LLM QC 处理。
    所有返回的 issue 带 source="rule"，用于确定性评分门槛。
    """
    issues = []
    text = record_text or ""

    def _make_issue(rule: dict) -> dict:
        return {
            "source": "rule",
            "issue_type": rule["issue_type"],
            "risk_level": rule["risk_level"],
            "field_name": rule["field_name"],
            "issue_description": rule["issue_description"],
            "suggestion": rule["suggestion"],
            "score_impact": rule.get("score_impact", ""),
        }

    # ── 通用规则 ────────────────────────────────────────────
    for rule in COMPLETENESS_RULES:
        keywords = rule.get("record_keywords", [])
        found = any(kw in text for kw in keywords) if keywords else False
        if not found:
            issues.append(_make_issue(rule))

    # ── 住院专用规则 ─────────────────────────────────────────
    if is_inpatient:
        for rule in INPATIENT_RULES:
            keywords = rule.get("record_keywords", [])
            found = any(kw in text for kw in keywords) if keywords else False
            if not found:
                issues.append(_make_issue(rule))

    # ── 复诊强制检查 ─────────────────────────────────────────
    if not is_first_visit:
        has_change = any(kw in text for kw in _REVISIT_SYMPTOM_CHANGE_KEYWORDS)
        if not has_change:
            issues.append({
                "source": "rule",
                "issue_type": "completeness",
                "risk_level": "high",
                "field_name": "history_present_illness",
                "issue_description": "复诊病历未记录治疗后症状改变情况——复诊必须记录上次治疗后症状的好转、无变化或加重情况（扣2分）",
                "suggestion": "请在现病史中补充上次治疗后的症状变化，如「经上次治疗后头痛明显缓解」",
                "score_impact": "-2分",
            })

    # 注意：中医四诊检查（舌象/脉象/证候诊断等）属于语义内容检查，已移至 LLM QC 处理，
    # 规则引擎不再检查，避免因写法格式不同产生误判。

    return issues
