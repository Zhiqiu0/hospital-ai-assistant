"""
初始化配置数据（seed_config.py）

执行内容：
  1. 清空并重新插入质控规则（qc_rules）
     - 完整性规则：依据《浙江省住院病历质量检查评分表（2021版）》
     - 医保风险规则：基于常见医保违规关键词
  2. 仅在 prompt_templates 表为空时插入默认 Prompt 模板

用法：
  cd backend
  python seed_config.py
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.database import engine

# ─────────────────────────────────────────────────────────────────────────────
# 质控规则种子数据
# 字段说明：
#   rule_code         — 唯一规则编码
#   name              — 规则名称（简短）
#   description       — 规则详细说明
#   rule_type         — completeness（完整性）/ insurance（医保风险）
#   scope             — all / inpatient / revisit / tcm
#   field_name        — 对应病历字段名（供前端高亮定位用）
#   keywords          — JSON 数组，病历中出现任一关键词即视为该字段已填写
#   indication_keywords — JSON 数组（仅 insurance 规则）：附近出现这些词则不报警
#   risk_level        — high / medium / low
#   issue_description — 质控问题描述（显示给医生）
#   suggestion        — 修改建议（显示给医生）
#   score_impact      — 扣分说明
# ─────────────────────────────────────────────────────────────────────────────

QC_RULES: list[dict] = [
    # ════════════════════════════════════════════════════════════════════════
    # 一、通用完整性规则（scope: all — 门诊 + 住院均适用）
    # 依据：浙江省住院病历质量检查评分表2021版 通用项
    # ════════════════════════════════════════════════════════════════════════
    {
        "rule_code": "CC001",
        "name": "主诉缺失",
        "description": "病历主诉字段为必填项，是患者就诊最核心的主观陈述",
        "rule_type": "completeness",
        "scope": "all",
        "field_name": "chief_complaint",
        "keywords": ["【主诉】", "主诉：", "主诉:"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "主诉未填写（扣1分）",
        "suggestion": "请填写患者主诉，格式：症状+持续时间，如「发现左手拇指近节指腹包块2月余」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC002",
        "name": "现病史缺失",
        "description": "现病史是病历核心内容，必须详述发病经过、症状特点及诊治过程",
        "rule_type": "completeness",
        "scope": "all",
        "field_name": "history_present_illness",
        "keywords": ["【现病史】", "现病史：", "现病史:"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "现病史未填写（扣2分）",
        "suggestion": "请详细描述现病史，包括：发病时间/地点/起病缓急、主要症状特点及演变、诊治经过、一般情况",
        "score_impact": "-2分",
    },
    {
        "rule_code": "CC003",
        "name": "既往史缺失",
        "description": "既往史记录患者过去的重要疾病史、手术外伤史、输血史等",
        "rule_type": "completeness",
        "scope": "all",
        "field_name": "past_history",
        "keywords": ["【既往史】", "既往史：", "既往史:"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "既往史未填写（扣0.5分）",
        "suggestion": "请填写既往史，如无特殊病史请填写「既往体质可，否认高血压、糖尿病、冠心病等慢性病史」",
        "score_impact": "-0.5分",
    },
    {
        "rule_code": "CC004",
        "name": "过敏史缺失",
        "description": "过敏史为高风险必填项，直接关系用药安全，缺失扣2分",
        "rule_type": "completeness",
        "scope": "all",
        "field_name": "allergy_history",
        "keywords": ["【过敏史】", "过敏史：", "过敏史:", "过敏", "否认药物", "否认食物"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "过敏史未填写——此项缺失直接扣2分（高风险）",
        "suggestion": "过敏史为必填项，如无过敏请填写「否认药物及食物过敏史」",
        "score_impact": "-2分",
    },
    {
        "rule_code": "CC005",
        "name": "体格检查缺失",
        "description": "体格检查结果为必填项，至少需包含生命体征及各系统检查",
        "rule_type": "completeness",
        "scope": "all",
        "field_name": "physical_exam",
        "keywords": ["【体格检查】", "体格检查：", "体格检查:"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "体格检查未填写（扣1分）",
        "suggestion": "请填写体格检查结果，至少包含生命体征（T/P/R/BP）及各系统检查",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC006",
        "name": "生命体征缺失",
        "description": "体格检查中必须记录体温(T)、脉搏(P)、呼吸(R)、血压(BP)四项生命体征",
        "rule_type": "completeness",
        "scope": "all",
        "field_name": "physical_exam_vitals",
        "keywords": ["T:", "T ", "体温", "P:", "P ", "脉搏", "R:", "R ", "呼吸", "BP:", "BP ", "血压"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "体格检查缺少生命体征记录（T/P/R/BP）（扣0.5分）",
        "suggestion": "请在体格检查中补充生命体征：T:__℃ P:__次/分 R:__次/分 BP:__/__mmHg",
        "score_impact": "-0.5分",
    },
    {
        "rule_code": "CC007",
        "name": "辅助检查缺失",
        "description": "辅助检查结果为必填项，如未行任何检查须注明「暂无」",
        "rule_type": "completeness",
        "scope": "all",
        "field_name": "auxiliary_exam",
        "keywords": ["【辅助检查】", "辅助检查：", "辅助检查:", "暂无检查", "暂无"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "辅助检查未填写——病历必须记录辅助检查结果，如无检查请填写「暂无」（扣1分）",
        "suggestion": "请填写辅助检查结果；如未行相关检查请填写「暂无」，不可留空",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC008",
        "name": "发病时间缺失",
        "description": "病历必须记录发病时间，是病程描述和医保审核的关键要素",
        "rule_type": "completeness",
        "scope": "all",
        "field_name": "onset_time",
        "keywords": ["病发时间", "发病时间", "起病时间", "onset"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "病发时间未填写——病历必须记录发病时间（扣1分）",
        "suggestion": "请填写病发时间，格式：YYYY-MM-DD HH:mm（24小时制阿拉伯数字）",
        "score_impact": "-1分",
    },
    # ════════════════════════════════════════════════════════════════════════
    # 二、住院病历专用完整性规则（scope: inpatient）
    # 依据：浙江省住院病历质量检查评分表2021版 住院病历专项
    # ════════════════════════════════════════════════════════════════════════
    {
        "rule_code": "CC009",
        "name": "婚育史缺失（住院）",
        "description": "住院病历必须记录婚育史，是全面了解患者背景的重要项目",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "marital_history",
        "keywords": ["【婚育史】", "婚育史：", "婚育史:", "未婚", "已婚", "离异", "丧偶"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "婚育史未填写——住院病历必填项（扣1分）",
        "suggestion": "请填写婚育史，如「25岁结婚，配偶体健，育有1子1女，均体健」或「未婚」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC010",
        "name": "家族史缺失（住院）",
        "description": "住院病历必须记录家族史，对遗传病、肿瘤等疾病诊断有重要参考价值",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "family_history",
        "keywords": ["【家族史】", "家族史：", "家族史:"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "家族史未填写——住院病历必填项（扣1分）",
        "suggestion": "请填写家族史，如「父母均健在，否认家族性遗传病、传染病史，否认肿瘤家族史」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC011",
        "name": "疼痛评估缺失（住院）",
        "description": "住院病历须包含NRS疼痛评分，是专项评估的必填内容",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "pain_assessment",
        "keywords": ["NRS评分", "NRS:", "NRS：", "疼痛评分", "疼痛评估", "疼痛NRS"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "专项评估缺少：疼痛评估（NRS评分）——缺1项扣1分",
        "suggestion": "请填写疼痛NRS评分（0-10分），如「NRS评分0分，无明显疼痛」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC012",
        "name": "VTE风险评估缺失（住院）",
        "description": "住院病历须包含静脉血栓栓塞（VTE）风险评估",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "vte_risk",
        "keywords": ["VTE", "静脉血栓", "血栓风险", "血栓栓塞"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "专项评估缺少：VTE（静脉血栓栓塞）风险评估——缺1项扣1分",
        "suggestion": "请填写VTE风险评估，如「VTE风险评估：低风险」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC013",
        "name": "营养风险评估缺失（住院）",
        "description": "住院病历须包含营养风险筛查（NRS2002等），缺失扣1分",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "nutrition_assessment",
        "keywords": ["营养评估", "营养风险", "NRS2002", "营养状态"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "专项评估缺少：营养风险评估——缺1项扣1分",
        "suggestion": "请填写营养评估，如「营养状态良好，无营养风险」或「NRS2002评分：__分」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC014",
        "name": "心理状态评估缺失（住院）",
        "description": "住院病历须包含心理状态评估，缺失扣1分",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "psychology_assessment",
        "keywords": ["心理评估", "心理状态", "PHQ", "焦虑", "抑郁评估"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "专项评估缺少：心理状态评估——缺1项扣1分",
        "suggestion": "请填写心理评估，如「心理状态良好，无焦虑抑郁」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC015",
        "name": "康复需求评估缺失（住院）",
        "description": "住院病历须包含康复需求评估，缺失扣1分",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "rehabilitation_assessment",
        "keywords": ["康复评估", "康复需求", "康复治疗需求"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "专项评估缺少：康复需求评估——缺1项扣1分",
        "suggestion": "请填写康复评估，如「无康复治疗需求」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC016",
        "name": "当前用药评估缺失（住院）",
        "description": "住院病历须记录患者入院前用药情况，缺失扣1分",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "current_medications",
        "keywords": ["用药评估", "当前用药", "长期用药", "否认长期用药", "用药情况"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "专项评估缺少：当前用药评估——缺1项扣1分",
        "suggestion": "请填写当前用药情况，如「否认长期用药史」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC017",
        "name": "宗教信仰/饮食禁忌缺失（住院）",
        "description": "住院病历须记录患者宗教信仰及饮食禁忌，缺失扣1分",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "religion_belief",
        "keywords": ["宗教", "饮食禁忌", "无宗教", "无饮食禁忌"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "专项评估缺少：宗教信仰/饮食禁忌评估——缺1项扣1分",
        "suggestion": "请填写宗教信仰或饮食禁忌，如「无宗教信仰，无饮食禁忌」",
        "score_impact": "-1分",
    },
    {
        "rule_code": "CC018",
        "name": "入院诊断缺失（住院）",
        "description": "住院病历必须明确记录入院诊断，缺失直接扣2分",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "admission_diagnosis",
        "keywords": ["【入院诊断】", "入院诊断：", "入院诊断:"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "入院诊断未填写（扣2分）",
        "suggestion": "请填写规范中文入院诊断，如「左拇指近节皮下肿物」，主要诊断放首位",
        "score_impact": "-2分",
    },
    {
        "rule_code": "CC019",
        "name": "个人史缺失（住院）",
        "description": "住院病历须记录生活习惯、职业史、疫区接触史等个人史",
        "rule_type": "completeness",
        "scope": "inpatient",
        "field_name": "personal_history",
        "keywords": ["【个人史】", "个人史：", "个人史:", "吸烟", "饮酒", "否认吸烟"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "个人史未填写——住院病历必填项（扣0.5分）",
        "suggestion": "请填写个人史，包括职业、生活习惯（吸烟/饮酒等），如「否认吸烟、饮酒史」",
        "score_impact": "-0.5分",
    },
    {
        "rule_code": "CC021",
        "name": "月经史缺失（住院·女性）",
        "description": "女性住院病历须记录月经史，包括末次月经、周期、经量等，是妇科及全科评估的必要内容",
        "rule_type": "completeness",
        "scope": "inpatient",
        "gender_scope": "female",
        "field_name": "menstrual_history",
        "keywords": ["月经史", "月经：", "月经:", "末次月经", "LMP", "绝经", "行经", "月经规律", "月经周期"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "月经史未填写——女性住院病历必填项（扣0.5分）",
        "suggestion": "请填写月经史，如「月经规律，周期28天，经期5天，LMP：XXXX-XX-XX」或「已绝经X年」",
        "score_impact": "-0.5分",
    },
    # ════════════════════════════════════════════════════════════════════════
    # 三、复诊病历专用规则（scope: revisit）
    # 依据：浙江省住院病历质量检查评分表2021版 复诊病历专项
    # ════════════════════════════════════════════════════════════════════════
    {
        "rule_code": "CC020",
        "name": "复诊未记录症状变化",
        "description": "复诊病历必须记录上次治疗后症状的好转/无变化/加重情况",
        "rule_type": "completeness",
        "scope": "revisit",
        "field_name": "history_present_illness",
        "keywords": [
            "治疗后", "服药后", "用药后", "针灸后", "推拿后",
            "好转", "改善", "缓解", "减轻", "消失", "加重", "无变化", "未见好转",
            "上次就诊", "上次治疗", "复诊", "经治疗",
            "症状变化", "症状改变", "病情变化",
        ],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "复诊病历未记录治疗后症状改变情况——复诊必须记录上次治疗后症状的好转、无变化或加重情况（扣2分）",
        "suggestion": "请在现病史中补充上次治疗后的症状变化，如「经上次治疗后头痛明显缓解」",
        "score_impact": "-2分",
    },
    # ════════════════════════════════════════════════════════════════════════
    # 四、中医病历专用规则（scope: tcm）
    # 依据：浙江省住院病历质量检查评分表2021版 中医病历专项
    # ════════════════════════════════════════════════════════════════════════
    {
        "rule_code": "TCM001",
        "name": "舌象缺失（中医）",
        "description": "中医病历必须记录舌质、舌苔，是四诊的核心内容之一",
        "rule_type": "completeness",
        "scope": "tcm",
        "field_name": "tongue_coating",
        "keywords": ["舌象", "舌质", "舌苔", "舌淡", "舌红", "舌暗", "舌胖"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【舌象】未填写——中医病历必须记录舌质、舌苔（扣2分）",
        "suggestion": "请填写舌象，格式如：舌淡红苔薄白；或：舌红苔黄腻",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM002",
        "name": "脉象缺失（中医）",
        "description": "中医病历必须记录脉象，是四诊的核心内容之一",
        "rule_type": "completeness",
        "scope": "tcm",
        "field_name": "pulse_condition",
        "keywords": ["脉象", "脉弦", "脉滑", "脉细", "脉数", "脉缓", "脉沉", "脉浮"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【脉象】未填写——中医病历必须记录脉象（扣2分）",
        "suggestion": "请填写脉象，格式如：脉弦细；或：脉滑数",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM003",
        "name": "中医证候诊断缺失（中医）",
        "description": "中医病历必须填写辨证分型，体现中医诊断的完整性",
        "rule_type": "completeness",
        "scope": "tcm",
        "field_name": "tcm_syndrome_diagnosis",
        "keywords": ["证候诊断：", "证候诊断:", "证型：", "证型:", "辨证："],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【中医证候诊断】未填写（扣2分）",
        "suggestion": "请填写中医证候诊断，格式如：肝阳上亢证；或：痰热壅肺证",
        "score_impact": "-2分",
    },
    {
        "rule_code": "TCM004",
        "name": "中医疾病诊断缺失（中医）",
        "description": "中医病历必须填写中医疾病诊断，与中医证候诊断一并构成中医诊断体系",
        "rule_type": "completeness",
        "scope": "tcm",
        "field_name": "tcm_disease_diagnosis",
        "keywords": ["中医诊断：", "中医诊断:", "疾病诊断：", "疾病诊断:"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【中医疾病诊断】未填写（扣1分）",
        "suggestion": "请填写中医疾病诊断，格式如：眩晕病；或：胸痹",
        "score_impact": "-1分",
    },
    {
        "rule_code": "TCM005",
        "name": "治则治法缺失（中医）",
        "description": "中医病历必须记录治则治法，指导处方用药及治疗方案",
        "rule_type": "completeness",
        "scope": "tcm",
        "field_name": "treatment_method",
        "keywords": ["治则", "治法", "治则治法"],
        "indication_keywords": [],
        "risk_level": "high",
        "issue_description": "病历含中医治疗，但【治则治法】未填写（扣1分）",
        "suggestion": "请填写治则治法，如：平肝潜阳、滋养肝肾",
        "score_impact": "-1分",
    },
    {
        "rule_code": "TCM006",
        "name": "望诊缺失（中医）",
        "description": "中医四诊（望闻问切）中望诊为必填内容",
        "rule_type": "completeness",
        "scope": "tcm",
        "field_name": "tcm_inspection",
        "keywords": ["望诊", "神色", "面色", "神清", "形态"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "病历含中医治疗，但【望诊】未填写（扣0.5分）",
        "suggestion": "请填写望诊内容，如：神清气爽，面色略红，体形中等",
        "score_impact": "-0.5分",
    },
    {
        "rule_code": "TCM007",
        "name": "闻诊缺失（中医）",
        "description": "中医四诊（望闻问切）中闻诊为必填内容",
        "rule_type": "completeness",
        "scope": "tcm",
        "field_name": "tcm_auscultation",
        "keywords": ["闻诊", "语声", "呼吸音", "气味"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "病历含中医治疗，但【闻诊】未填写（扣0.5分）",
        "suggestion": "请填写闻诊内容，如：语声清晰，无异常气味",
        "score_impact": "-0.5分",
    },
    # ════════════════════════════════════════════════════════════════════════
    # 五、医保风险规则（rule_type: insurance）
    # 依据：国家医保局病历检查常见违规项目
    # ════════════════════════════════════════════════════════════════════════

    # ── 高值检查项目（需有明确适应症）──────────────────────────────────────
    {
        "rule_code": "INS001",
        "name": "MRI/核磁共振未注明适应症",
        "description": "MRI检查费用较高，医保审核要求病历中必须有明确的检查适应症",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["MRI", "核磁", "磁共振"],
        "indication_keywords": ["因", "由于", "考虑", "诊断", "为明确", "排除", "评估", "适应"],
        "risk_level": "medium",
        "issue_description": "病历中记录了MRI/核磁共振检查，但附近未见明确适应症描述",
        "suggestion": "请在MRI检查前补充医学必要性说明，如「为明确颅内占位性质」或「因头痛原因待查，行MRI评估」",
        "score_impact": "",
    },
    {
        "rule_code": "INS002",
        "name": "增强CT未注明适应症",
        "description": "增强CT为高值检查，医保要求有明确适应症记录",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["增强CT", "CT增强"],
        "indication_keywords": ["因", "由于", "考虑", "诊断", "为明确", "排除", "评估", "适应"],
        "risk_level": "medium",
        "issue_description": "病历中记录了增强CT，但附近未见明确适应症描述",
        "suggestion": "请在增强CT前补充医学必要性说明，如「为明确肿块性质，排除恶性病变」",
        "score_impact": "",
    },
    {
        "rule_code": "INS003",
        "name": "PET-CT未注明适应症",
        "description": "PET-CT属高值检查，医保审核严格，必须有明确肿瘤分期或治疗评估的适应症",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["PET", "PET-CT", "PET/CT"],
        "indication_keywords": ["因", "由于", "考虑", "诊断", "为明确", "排除", "评估", "分期", "适应"],
        "risk_level": "high",
        "issue_description": "病历中记录了PET-CT检查，但附近未见明确适应症描述（高风险）",
        "suggestion": "请明确PET-CT的医学必要性，如「为明确肿瘤分期及远处转移情况」",
        "score_impact": "",
    },
    {
        "rule_code": "INS004",
        "name": "内镜检查未注明适应症",
        "description": "内镜（胃镜/肠镜/支气管镜等）需有明确症状或筛查依据",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["内镜", "胃镜", "肠镜", "支气管镜", "膀胱镜"],
        "indication_keywords": ["因", "由于", "考虑", "诊断", "为明确", "排除", "评估", "适应", "症状"],
        "risk_level": "medium",
        "issue_description": "病历中记录了内镜检查，但附近未见明确适应症描述",
        "suggestion": "请在内镜检查前补充医学必要性，如「因上腹痛反复发作，为排除消化道溃疡行胃镜检查」",
        "score_impact": "",
    },
    {
        "rule_code": "INS005",
        "name": "骨髓穿刺未注明适应症",
        "description": "骨髓穿刺为有创检查，医保要求明确的血液病诊断依据",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["骨髓穿刺", "骨穿"],
        "indication_keywords": ["因", "由于", "考虑", "诊断", "为明确", "排除", "血液病", "贫血", "白血病"],
        "risk_level": "high",
        "issue_description": "病历中记录了骨髓穿刺，但附近未见明确适应症描述",
        "suggestion": "请明确骨髓穿刺指征，如「因血常规异常，WBC持续升高，为明确诊断行骨髓穿刺」",
        "score_impact": "",
    },
    {
        "rule_code": "INS006",
        "name": "腰椎穿刺未注明适应症",
        "description": "腰椎穿刺为有创检查，需有明确的神经系统疾病诊断依据",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["腰椎穿刺", "腰穿"],
        "indication_keywords": ["因", "由于", "考虑", "诊断", "为明确", "排除", "脑膜炎", "蛛网膜下腔"],
        "risk_level": "high",
        "issue_description": "病历中记录了腰椎穿刺，但附近未见明确适应症描述",
        "suggestion": "请明确腰椎穿刺指征，如「因发热伴头痛，疑颅内感染，为明确病原行腰穿脑脊液检查」",
        "score_impact": "",
    },
    # ── 高风险药物（需有明确用药指征）─────────────────────────────────────
    {
        "rule_code": "INS007",
        "name": "人血白蛋白未注明指征",
        "description": "人血白蛋白为高值药物，医保严格审查，须有低蛋白血症等明确指征",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["人血白蛋白", "白蛋白注射液"],
        "indication_keywords": ["因", "用于", "治疗", "低蛋白", "白蛋白低", "低于", "营养不良", "肝硬化"],
        "risk_level": "high",
        "issue_description": "使用了人血白蛋白，但未见明确用药指征",
        "suggestion": "请补充人血白蛋白的用药依据，如「血清白蛋白20g/L，存在低蛋白血症，予人血白蛋白纠正」",
        "score_impact": "",
    },
    {
        "rule_code": "INS008",
        "name": "丙种球蛋白未注明指征",
        "description": "丙种球蛋白为高值药物，需有免疫缺陷或特定感染性疾病的明确指征",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["丙种球蛋白", "静注人免疫球蛋白"],
        "indication_keywords": ["因", "用于", "治疗", "适用于", "免疫缺陷", "川崎", "重症感染", "ITP"],
        "risk_level": "high",
        "issue_description": "使用了丙种球蛋白，但未见明确用药指征",
        "suggestion": "请补充丙种球蛋白的用药依据，如「诊断川崎病，予IVIG冲击治疗」",
        "score_impact": "",
    },
    {
        "rule_code": "INS009",
        "name": "促红细胞生成素未注明指征",
        "description": "重组人促红细胞生成素为高值生物制剂，需有肾性贫血等明确指征",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["促红细胞生成素", "EPO", "重组人EPO"],
        "indication_keywords": ["因", "用于", "治疗", "肾性贫血", "血液透析", "贫血", "Hb"],
        "risk_level": "high",
        "issue_description": "使用了促红细胞生成素，但未见明确用药指征",
        "suggestion": "请补充EPO的用药依据，如「慢性肾病患者Hb 80g/L，存在肾性贫血，予重组人EPO治疗」",
        "score_impact": "",
    },
    {
        "rule_code": "INS010",
        "name": "奥美拉唑注射液未注明指征",
        "description": "奥美拉唑注射液（质子泵抑制剂）需有消化道出血或高风险手术等明确指征",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["奥美拉唑注射液", "泮托拉唑注射液", "兰索拉唑注射液"],
        "indication_keywords": ["因", "用于", "消化道出血", "手术预防", "应激性溃疡", "出血", "上消化道"],
        "risk_level": "medium",
        "issue_description": "使用了质子泵抑制剂注射液，但未见明确适应症（消化道出血/手术预防）",
        "suggestion": "请补充PPI注射液的用药依据，或改用口服制剂（无出血风险时注射剂型属超适应症）",
        "score_impact": "",
    },
    {
        "rule_code": "INS011",
        "name": "输血浆未注明指征",
        "description": "血浆输注需有凝血功能障碍等明确临床指征，无指征输血为医保违规",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["输血浆", "新鲜冰冻血浆", "FFP"],
        "indication_keywords": ["因", "用于", "凝血", "PT延长", "APTT", "凝血因子", "出血", "手术"],
        "risk_level": "high",
        "issue_description": "病历记录了输血浆，但未见明确输血指征",
        "suggestion": "请补充输血浆的临床依据，如「PT明显延长，存在凝血功能障碍，予FFP输注」",
        "score_impact": "",
    },
    # ── 不当表述（直接触发，无上下文豁免）─────────────────────────────────
    {
        "rule_code": "INS012",
        "name": "以家属要求为治疗依据",
        "description": "病历中记录'家属要求'作为治疗依据，医保不予认可，可能导致拒付",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["家属要求", "家属坚持要求"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "病历中以「家属要求」作为治疗依据——医保通常不认可，可能导致拒付",
        "suggestion": "请将「家属要求」改为「家属知情同意」或补充医学必要性说明，如「基于病情需要，经家属知情同意后行…」",
        "score_impact": "",
    },
    {
        "rule_code": "INS013",
        "name": "以患者要求为治疗依据",
        "description": "病历中记录'患者要求'作为治疗依据，医保不予认可",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["患者要求", "患者坚持"],
        "indication_keywords": [],
        "risk_level": "medium",
        "issue_description": "病历中以「患者要求」作为治疗依据——应写明医学适应症",
        "suggestion": "请补充医学必要性说明，将「患者要求」改为具体的医学指征描述",
        "score_impact": "",
    },
    {
        "rule_code": "INS014",
        "name": "预防性用药无适应症说明",
        "description": "预防性用药需有明确适应症，否则医保可能拒付",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["预防性使用", "预防用药", "预防性应用"],
        "indication_keywords": ["高风险", "感染风险", "手术", "免疫抑制", "化疗后", "适应症"],
        "risk_level": "medium",
        "issue_description": "病历中记录了预防性用药，但未见明确适应症说明",
        "suggestion": "请补充预防性用药的临床依据，如「患者免疫功能低下，存在感染高风险，予预防性抗感染治疗」",
        "score_impact": "",
    },
    {
        "rule_code": "INS015",
        "name": "自费项目记录不规范",
        "description": "病历中出现'自费'字样，需确认是否为正确的费用分类记录",
        "rule_type": "insurance",
        "scope": "all",
        "field_name": "content",
        "keywords": ["自费", "自付"],
        "indication_keywords": [],
        "risk_level": "low",
        "issue_description": "病历含有「自费」字样，请确认费用分类记录是否规范",
        "suggestion": "请核查该自费项目是否已按规定记录，避免因费用分类不当导致医保审核问题",
        "score_impact": "",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# 默认 Prompt 模板种子数据
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATES: list[dict] = [
    {
        "name": "门诊病历生成-标准版",
        "scene": "generate",
        "content": (
            "你是一名专业的临床病历书写助手。根据问诊信息生成标准化门诊病历。"
            "要求：口语转书面医学语言，时间线清晰，符合医疗文书规范，禁止编造未提及内容。"
        ),
        "version": "v1",
    },
    {
        "name": "病历润色-标准版",
        "scene": "polish",
        "content": (
            "你是临床病历规范化专家。对病历进行润色：口语转书面语，消除重复，优化逻辑，"
            "保持术语准确。禁止添加未提及内容。"
        ),
        "version": "v1",
    },
    {
        "name": "追问建议-标准版",
        "scene": "inquiry",
        "content": (
            "你是临床问诊助手。根据问诊信息给出3-5条追问建议，帮助医生补充关键信息。"
            "关注危险信号、病程特征、伴随症状。"
        ),
        "version": "v1",
    },
    {
        "name": "AI质控-标准版",
        "scene": "qc",
        "content": (
            "你是临床病历质控专家。检查病历完整性、规范性和逻辑性，"
            "找出缺漏和不规范之处，按高中低危分级输出。"
        ),
        "version": "v1",
    },
]


async def seed() -> None:
    """执行种子数据初始化。"""
    # 需要在本地导入，避免顶层循环导入
    from app.models.config import QCRule, PromptTemplate  # noqa

    async with AsyncSession(engine) as session:

        # ── 1. 质控规则：清空后重新插入（ORM 方式，避免 asyncpg 参数语法冲突）──
        await session.execute(text("DELETE FROM qc_rules"))
        print("[清空] qc_rules 表已清空")

        for rule in QC_RULES:
            obj = QCRule(
                rule_code=rule["rule_code"],
                name=rule["name"],
                description=rule.get("description"),
                rule_type=rule["rule_type"],
                scope=rule.get("scope", "all"),
                gender_scope=rule.get("gender_scope", "all"),
                field_name=rule.get("field_name"),
                keywords=rule.get("keywords") or [],
                indication_keywords=rule.get("indication_keywords") or [],
                risk_level=rule.get("risk_level", "medium"),
                issue_description=rule.get("issue_description"),
                suggestion=rule.get("suggestion"),
                score_impact=rule.get("score_impact"),
                is_active=True,
            )
            session.add(obj)

        await session.flush()
        print(f"[OK] 插入 {len(QC_RULES)} 条质控规则")

        # ── 2. Prompt 模板：仅在表为空时插入 ────────────────────────────────
        r = await session.execute(text("SELECT COUNT(*) FROM prompt_templates"))
        if r.scalar() == 0:
            for tmpl in PROMPT_TEMPLATES:
                obj = PromptTemplate(
                    name=tmpl["name"],
                    scene=tmpl.get("scene"),
                    content=tmpl["content"],
                    version=tmpl.get("version", "v1"),
                    is_active=True,
                )
                session.add(obj)
            print(f"[OK] 插入 {len(PROMPT_TEMPLATES)} 条默认 Prompt 模板")
        else:
            print("[SKIP] prompt_templates 已有数据，跳过")

        await session.commit()
        print("[完成] 种子数据初始化完毕")


if __name__ == "__main__":
    asyncio.run(seed())
