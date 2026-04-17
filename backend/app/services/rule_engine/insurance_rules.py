"""
医保风险规则引擎（DB 驱动）

职责：
  扫描病历文本，发现可能触发医保拒付或违规的关键词，返回风险警告。
  纯关键词/上下文检测，不做语义判断（语义风险由 LLM QC 负责）。

规则数据来源：
  qc_rules 表中 rule_type='insurance' 的激活规则。

执行逻辑（每条规则独立判断）：
  1. 遍历 keywords 列表，查找触发词在病历中的 **所有出现位置**
  2. 对每个出现位置检查 ±80 字符上下文：
     - indication_keywords 为空 → 触发词出现即报警（无条件）
     - indication_keywords 非空 → 上下文中 **任意一处** 均无适应症词才报警
  3. 同一规则只报警一次（找到首个符合条件的位置即 break）

修复说明（Bug C）：
  原代码用 content.find(kw) 只检查第一次出现位置。
  若同一药名在病历中出现多次（如第一次在"既往史"附近有适应症词，
  第二次在"治疗方案"处没有），原代码会漏报第二次。
  修复后改用 _find_all_positions() 检查所有位置，任意一处无适应症即报警。
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


def _find_all_positions(text: str, keyword: str) -> list[int]:
    """返回 keyword 在 text 中所有出现位置的起始索引列表。

    不使用正则，直接逐字符搜索，适合中文关键词匹配。
    """
    positions = []
    start = 0
    while True:
        pos = text.find(keyword, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 1  # 允许重叠匹配，逐字符推进
    return positions


def _has_indication_nearby(text: str, trigger_pos: int, indication_keywords: list) -> bool:
    """在触发词前后 ±_CONTEXT_WINDOW 字符范围内查找适应症关键词。

    Args:
        text:                病历全文。
        trigger_pos:         触发词在 text 中的起始位置。
        indication_keywords: 适应症关键词列表；有任意一个出现即认为有适应症。

    Returns:
        True  → 附近有适应症词，不需要报警；
        False → 附近无适应症词，应当报警。
    """
    ctx_start = max(0, trigger_pos - _CONTEXT_WINDOW)
    ctx_end = min(len(text), trigger_pos + _CONTEXT_WINDOW)
    context = text[ctx_start:ctx_end]
    return any(kw in context for kw in indication_keywords)


async def check_insurance_risk(content: str, db: AsyncSession) -> list[dict]:
    """对病历文本进行医保风险扫描，返回风险问题列表。

    只做关键词 / 上下文检测，不做语义判断（语义判断由 LLM 负责）。

    Args:
        content: 病历全文。
        db:      数据库会话，用于加载 qc_rules 表中的医保规则。

    Returns:
        风险问题字典列表，每项含 source/issue_type/risk_level 等字段。
    """
    if not content or len(content.strip()) < 20:
        return []

    # 加载所有激活的医保风险规则（按 rule_code 排序保证输出顺序稳定）
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
        rule_triggered = False  # 同一规则只报警一次

        for kw in keywords:
            if rule_triggered:
                break

            # BUG FIX: 原代码 content.find(kw) 只检查第一次出现，
            # 若第一次附近有适应症词则跳过，但后续出现漏检。
            # 修复：获取关键词所有出现位置，逐一检查上下文。
            positions = _find_all_positions(content, kw)
            if not positions:
                continue  # 此触发词不在病历中，检查下一个

            if not indication_keywords:
                # 无条件触发：只要触发词出现就报警，无需检查上下文
                issues.append({
                    "source": "rule",
                    "issue_type": "insurance",
                    "risk_level": rule.risk_level,
                    "field_name": rule.field_name or "content",
                    "issue_description": rule.issue_description or rule.name,
                    "suggestion": rule.suggestion or "",
                    "score_impact": rule.score_impact or "",
                })
                rule_triggered = True
            else:
                # 有适应症词列表：检查每个出现位置，任意一处无适应症即报警
                for pos in positions:
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
                        rule_triggered = True
                        break  # 已报警，不重复处理同一规则

    return issues
