"""
完整性质控规则引擎（DB 驱动）

规则数据从 qc_rules 表动态加载（rule_type='completeness'）。

匹配逻辑（两层，优先级依次降低）：
  1. 章节名匹配（section_names）：把病历按【XXX】解析成章节 Map，
     检查章节是否存在且有非空内容。与格式完全无关，最健壮。
  2. 关键词兜底（keywords）：在原始文本里做字符串包含检查，
     用于无法用章节名表达的规则（如生命体征、住院评估等）。

规则定义时：
  - 能用章节名的优先写 section_names（存在 keywords 字段中，以 "§" 前缀区分）
  - 其余情况用 keywords 做文本匹配

scope 过滤：
  - all      → 始终执行
  - inpatient → is_inpatient=True 时才执行
  - revisit  → is_first_visit=False 时才执行
  - tcm      → 病历含中医章节时才执行
"""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import QCRule

logger = logging.getLogger(__name__)

# 章节前缀标记：keywords 中以此开头的条目视为章节名，走章节解析逻辑
_SECTION_PREFIX = "§"

# 中医相关章节名，用于判断病历是否含中医内容
_TCM_SECTION_NAMES = {"中医诊断", "中医证候诊断", "中医疾病诊断", "舌象", "脉象", "中医四诊"}

# 中医诊疗行为关键词，作为补充判断（章节名优先）
_TCM_ACTION_KEYWORDS = [
    "中药", "针灸", "推拿", "中医治疗", "辨证", "中药汤剂", "中成药",
    "穴位", "艾灸", "拔罐", "刮痧", "草药", "治则治法",
]


def parse_sections(text: str) -> dict[str, str]:
    """
    把病历全文按【章节名】解析为 {章节名: 内容} 的字典。
    内容为该章节标题到下一个章节标题之间的文字（去除首尾空白）。
    """
    sections: dict[str, str] = {}
    # 匹配所有【XXX】标题及其位置
    pattern = re.compile(r'【([^】]+)】')
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections[name] = content
    return sections


def _is_tcm_record(text: str, sections: dict[str, str]) -> bool:
    """判断病历是否含中医内容：优先检查章节名，其次检查诊疗行为关键词。"""
    if any(name in sections for name in _TCM_SECTION_NAMES):
        return True
    return any(kw in text for kw in _TCM_ACTION_KEYWORDS)


def _check_rule(rule: QCRule, text: str, sections: dict[str, str]) -> bool:
    """
    检查单条规则是否命中（即内容是否存在）。
    返回 True 表示找到，False 表示缺失（触发问题）。

    keywords 中：
      - 以 § 开头的条目 → 章节名匹配（章节存在且有内容）
      - 其余条目       → 原始文本包含检查
    任意一项命中即视为存在。
    """
    keywords = rule.keywords or []
    if not keywords:
        return True  # 无关键词的规则不触发

    for kw in keywords:
        if kw.startswith(_SECTION_PREFIX):
            # §章节名 → 章节解析
            section_name = kw[len(_SECTION_PREFIX):]
            if section_name in sections and sections[section_name]:
                return True
        elif kw.startswith('【') and kw.endswith('】'):
            # 【章节名】 → 自动识别为章节解析（向后兼容旧格式）
            section_name = kw[1:-1]
            if section_name in sections and sections[section_name]:
                return True
        else:
            # 原始文本包含匹配（兜底，用于生命体征等无章节名的规则）
            if kw in text:
                return True
    return False


def _make_issue(rule: QCRule) -> dict:
    """将 QCRule ORM 对象转换为质控问题字典。"""
    return {
        "source": "rule",
        "issue_type": "completeness",
        "risk_level": rule.risk_level,
        "field_name": rule.field_name or "",
        "issue_description": rule.issue_description or rule.name,
        "suggestion": rule.suggestion or "",
        "score_impact": rule.score_impact or "",
    }


async def check_completeness(
    record_text: str,
    db: AsyncSession,
    is_inpatient: bool = False,
    is_first_visit: bool = True,
    patient_gender: str = "",
) -> list:
    """
    规则引擎：对病历文本做结构性完整性检查。

    - 优先用章节解析（§前缀）确定字段是否存在，与格式无关
    - 无章节名的规则退化为关键词文本匹配
    - 所有 issue 带 source='rule'，用于确定性评分门槛
    """
    text = record_text or ""
    issues: list = []

    # 一次性解析章节，供所有规则复用
    sections = parse_sections(text)

    # 加载所有激活的完整性规则（Redis 缓存 60s，admin 写时主动失效）
    try:
        from app.services.qc_rules_cache import get_active_qc_rules
        rules = await get_active_qc_rules(db, "completeness")
    except Exception as exc:
        logger.error("rules.completeness: load_failed err=%s", exc)
        return []

    is_tcm = _is_tcm_record(text, sections)

    for rule in rules:
        scope = rule.scope or "all"
        gender_scope = getattr(rule, "gender_scope", "all") or "all"

        # scope 过滤
        if scope == "inpatient" and not is_inpatient:
            continue
        if scope == "revisit" and is_first_visit:
            continue
        if scope == "tcm" and not is_tcm:
            continue

        # 性别过滤：未知性别或性别不匹配时跳过限定规则
        if gender_scope != "all" and (not patient_gender or gender_scope != patient_gender):
            continue

        if not _check_rule(rule, text, sections):
            issues.append(_make_issue(rule))

    return issues
