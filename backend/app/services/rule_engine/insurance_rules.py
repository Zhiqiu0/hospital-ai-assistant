"""
医保风险规则引擎
基于关键词和模式检测病历中可能存在的医保合规风险
"""
import re

# 高值检查/治疗关键词 — 需要明确适应症记录
HIGH_VALUE_ITEMS = [
    ("MRI", "核磁共振（MRI）"),
    ("核磁", "核磁共振"),
    ("磁共振", "磁共振检查"),
    ("增强CT", "增强CT扫描"),
    ("PET", "PET-CT"),
    ("内镜", "内镜检查"),
    ("胃镜", "胃镜检查"),
    ("肠镜", "肠镜检查"),
    ("骨髓穿刺", "骨髓穿刺"),
    ("腰椎穿刺", "腰椎穿刺"),
    ("心导管", "心导管检查"),
]

# 高风险用药关键词 — 需要有明确诊断依据
HIGH_RISK_DRUGS = [
    ("人血白蛋白", "人血白蛋白"),
    ("丙种球蛋白", "丙种球蛋白"),
    ("重组人促红细胞生成素", "促红细胞生成素"),
    ("奥美拉唑注射液", "奥美拉唑注射液（需有消化道出血或手术预防依据）"),
    ("血浆", "血浆输注"),
]

# 住院相关高风险词
INPATIENT_RISK_PATTERNS = [
    (r"住院.*?(\d+)\s*天", "住院天数"),
    (r"手术", "手术治疗"),
]

# 表述不当关键词（可能导致医保拒付）
INVALID_PHRASES = [
    ("家属要求", "记录'家属要求'为治疗依据——医保通常不认可，应写明医学必要性"),
    ("患者要求", "记录'患者要求'为治疗依据——应写明医学适应症"),
    ("预防性使用", "预防性用药需有明确适应症，否则医保可拒付"),
    ("自费", "病历中出现'自费'字样，确认记录是否规范"),
]


def check_insurance_risk(content: str) -> list[dict]:
    """
    对病历文本进行医保风险扫描，返回风险列表。
    只做关键词/模式检测，不做语义判断（语义由LLM负责）。
    """
    if not content or len(content.strip()) < 20:
        return []

    issues = []

    # 1. 高值检查 — 检查是否出现但缺少适应症描述
    for keyword, display_name in HIGH_VALUE_ITEMS:
        if keyword in content:
            # 简单启发：如果附近没有"因为"/"由于"/"适应症"/"诊断"等词，则标记
            context_start = max(0, content.find(keyword) - 80)
            context_end = min(len(content), content.find(keyword) + 80)
            context = content[context_start:context_end]
            has_indication = any(w in context for w in ["因", "由于", "考虑", "诊断", "为明确", "排除", "评估", "适应"])
            if not has_indication:
                issues.append({
                    "issue_type": "insurance",
                    "risk_level": "medium",
                    "field_name": "content",
                    "issue_description": f"病历中记录了{display_name}，但附近未见明确适应症描述",
                    "suggestion": f"请在{display_name}前补充医学必要性说明，如“为明确某项诊断”或“因某项适应症行相关检查”",
                })

    # 2. 高风险用药
    for keyword, display_name in HIGH_RISK_DRUGS:
        if keyword in content:
            context_start = max(0, content.find(keyword) - 60)
            context_end = min(len(content), content.find(keyword) + 60)
            context = content[context_start:context_end]
            has_indication = any(w in context for w in ["因", "用于", "治疗", "适用于", "低蛋白", "出血", "手术"])
            if not has_indication:
                issues.append({
                    "issue_type": "insurance",
                    "risk_level": "high",
                    "field_name": "content",
                    "issue_description": f"使用了高值药物“{display_name}”，但未见明确用药指征",
                    "suggestion": f"请补充“{display_name}”的用药依据，否则可能面临医保拒付风险",
                })

    # 3. 不当表述
    for phrase, description in INVALID_PHRASES:
        if phrase in content:
            issues.append({
                "issue_type": "insurance",
                "risk_level": "medium",
                "field_name": "content",
                "issue_description": f"病历含有医保高风险表述：“{phrase}”",
                "suggestion": description,
            })

    return issues
