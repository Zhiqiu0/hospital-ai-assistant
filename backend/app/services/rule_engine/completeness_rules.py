"""
完整性质控规则引擎（DB 驱动）

规则数据从 qc_rules 表动态加载（rule_type='completeness'）。
执行逻辑：检查 keywords 列表中是否有任一关键词出现在病历文本中；
未出现则触发该规则，输出带 source='rule' 的问题条目。

scope 过滤：
  - all      → 始终执行
  - inpatient → is_inpatient=True 时才执行
  - revisit   → is_first_visit=False 时才执行
  - tcm       → 病历文本含中医关键词时才执行
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.config import QCRule

logger = logging.getLogger(__name__)

# 检测病历是否含中医内容的关键词
_TCM_DETECTION_KEYWORDS = [
    # 章节标题或诊断标签（带括号或冒号才算，避免"中医诊断"裸词误触发）
    "【中医诊断】", "中医诊断：", "中医诊断:",
    "证候诊断：", "证候诊断:", "证型：", "证型:",
    # 明确中医诊疗行为
    "中药", "针灸", "推拿", "中医治疗", "辨证", "中药汤剂", "中成药",
    "中药方", "中药饮片", "穴位", "艾灸", "拔罐", "刮痧", "草药", "治则治法",
]


def _is_tcm_record(text: str) -> bool:
    """判断病历文本是否含有中医内容。"""
    return any(kw in text for kw in _TCM_DETECTION_KEYWORDS)


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
    规则引擎：对病历文本做结构性完整性检查（有没有该章节/字段）。

    - 只检查字段/章节是否存在（关键词有无），不做语义内容质量评估
    - 所有返回 issue 带 source='rule'，用于确定性评分门槛
    - 语义检查（中医四诊规范性、诊断准确性等）交由 LLM QC 处理

    Args:
        record_text: 病历全文
        db: 数据库会话（用于加载 qc_rules 表中的规则）
        is_inpatient: 是否为住院病历
        is_first_visit: 是否为初诊（False 则同时执行复诊规则）
        patient_gender: 患者性别（'male'/'female'/''），用于过滤 gender_scope 规则
    """
    text = record_text or ""
    issues: list = []

    # 加载所有激活的完整性规则
    try:
        result = await db.execute(
            select(QCRule).where(
                QCRule.rule_type == "completeness",
                QCRule.is_active.is_(True),
            ).order_by(QCRule.rule_code)
        )
        rules: list[QCRule] = list(result.scalars().all())
    except Exception as exc:
        logger.error("check_completeness: failed to load rules from DB: %s", exc)
        return []

    is_tcm = _is_tcm_record(text)

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

        # 性别过滤：gender_scope 非 all 时，患者性别必须匹配才触发
        if gender_scope != "all" and patient_gender and gender_scope != patient_gender:
            continue
        # 性别未知（patient_gender 为空）时跳过性别限定规则，避免误报
        if gender_scope != "all" and not patient_gender:
            continue

        keywords = rule.keywords or []
        found = any(kw in text for kw in keywords) if keywords else False
        if not found:
            issues.append(_make_issue(rule))

    return issues
