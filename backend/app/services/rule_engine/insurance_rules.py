"""
医保风险规则引擎（DB 驱动）

规则数据从 qc_rules 表动态加载（rule_type='insurance'）。
执行逻辑：
  1. 检查 keywords 中是否有触发词出现在病历文本中
  2. 若触发词存在，再在触发词前后 ±80 字符的上下文中查找 indication_keywords
     - indication_keywords 为空 → 只要触发词出现即报警（无条件触发）
     - indication_keywords 非空 → 上下文中未见适应症词才报警
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.config import QCRule

logger = logging.getLogger(__name__)

# 触发词前后的上下文窗口大小（字符数）
_CONTEXT_WINDOW = 80


def _has_indication_nearby(text: str, trigger_pos: int, indication_keywords: list) -> bool:
    """在触发词前后 ±_CONTEXT_WINDOW 字符范围内查找适应症关键词。"""
    ctx_start = max(0, trigger_pos - _CONTEXT_WINDOW)
    ctx_end = min(len(text), trigger_pos + _CONTEXT_WINDOW)
    context = text[ctx_start:ctx_end]
    return any(kw in context for kw in indication_keywords)


async def check_insurance_risk(content: str, db: AsyncSession) -> list[dict]:
    """
    对病历文本进行医保风险扫描，返回风险问题列表。

    只做关键词 / 上下文检测，不做语义判断（语义判断由 LLM 负责）。

    Args:
        content: 病历全文
        db: 数据库会话（用于加载 qc_rules 表中的医保规则）
    """
    if not content or len(content.strip()) < 20:
        return []

    # 加载所有激活的医保风险规则
    try:
        result = await db.execute(
            select(QCRule).where(
                QCRule.rule_type == "insurance",
                QCRule.is_active.is_(True),
            ).order_by(QCRule.rule_code)
        )
        rules: list[QCRule] = list(result.scalars().all())
    except Exception as exc:
        logger.error("check_insurance_risk: failed to load rules from DB: %s", exc)
        return []

    issues: list[dict] = []

    for rule in rules:
        keywords = rule.keywords or []
        indication_keywords = rule.indication_keywords or []

        for kw in keywords:
            pos = content.find(kw)
            if pos == -1:
                continue  # 触发词不在病历中

            # 无条件触发（indication_keywords 为空）
            if not indication_keywords:
                issues.append({
                    "source": "rule",
                    "issue_type": "insurance",
                    "risk_level": rule.risk_level,
                    "field_name": rule.field_name or "content",
                    "issue_description": rule.issue_description or rule.name,
                    "suggestion": rule.suggestion or "",
                    "score_impact": rule.score_impact or "",
                })
                break  # 同一规则不重复报警

            # 上下文检查：附近有适应症词则不报警
            if not _has_indication_nearby(content, pos, indication_keywords):
                issues.append({
                    "source": "rule",
                    "issue_type": "insurance",
                    "risk_level": rule.risk_level,
                    "field_name": rule.field_name or "content",
                    "issue_description": rule.issue_description or rule.name,
                    "suggestion": rule.suggestion or "",
                    "score_impact": rule.score_impact or "",
                })
                break  # 同一规则不重复报警

    return issues
