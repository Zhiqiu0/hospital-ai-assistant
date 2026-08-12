"""QC 规则 Redis 缓存层（services/qc_rules_cache.py）

规则引擎每次质控都查 qc_rules 表（按 rule_type + is_active 过滤），
完整性规则和医保规则共用本模块。

设计：
  - 把 ORM 序列化为 dict 写 Redis
  - 读取时还原成 SimpleNamespace，让规则引擎用属性访问保持无感知
  - 缓存靠 TTL 自然过期（admin 在线编辑规则的端点已下线，无主动失效需求）
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import QCRule
from app.services.redis_cache import redis_cache

# 规则缓存 key：按 rule_type 区分（completeness / insurance）
_KEY = "qc:rules:{rule_type}"
_TTL = 60  # 60 秒，admin 写规则时主动失效

# QCRule 需要序列化的字段（与规则引擎实际访问的属性集合保持同步）
_RULE_FIELDS = (
    "id",
    "rule_code",
    "name",
    "description",
    "rule_type",
    "scope",
    "gender_scope",
    "field_name",
    "keywords",
    "indication_keywords",
    "risk_level",
    "issue_description",
    "suggestion",
    "score_impact",
    "is_active",
)


def _serialize(rule: QCRule) -> dict:
    """ORM → dict（仅取规则引擎用到的字段）。"""
    return {f: getattr(rule, f, None) for f in _RULE_FIELDS}


def _deserialize(data: dict) -> SimpleNamespace:
    """dict → SimpleNamespace（属性访问与 ORM 兼容）。"""
    return SimpleNamespace(**data)


async def get_active_qc_rules(db: AsyncSession, rule_type: str) -> list[SimpleNamespace]:
    """获取指定类型的全部激活规则（带 Redis 缓存 60 秒）。

    Args:
        db:        异步数据库会话（缓存未命中时 fallback 查库）。
        rule_type: "completeness" 或 "insurance"。

    Returns:
        规则对象列表，可像 ORM 一样属性访问（rule.risk_level / rule.keywords 等）。
        Redis 不可用或 DB 异常时返回空列表，调用方按"无规则"处理（不会误报）。
    """
    cache_key = _KEY.format(rule_type=rule_type)
    cached = await redis_cache.get_json(cache_key)
    if cached is not None:
        return [_deserialize(item) for item in cached]

    result = await db.execute(
        select(QCRule).where(
            QCRule.rule_type == rule_type,
            QCRule.is_active.is_(True),
        ).order_by(QCRule.rule_code)
    )
    rules = list(result.scalars().all())
    serialized = [_serialize(r) for r in rules]
    await redis_cache.set_json(cache_key, serialized, ttl=_TTL)
    return [_deserialize(item) for item in serialized]


# 注：原 invalidate_qc_rules（admin 写规则后失效缓存）已删（2026-08-12 复检清理）——
# admin 在线编辑 qc_rules 的端点早已下线（评分标准走代码常量），该函数零调用方；
# 医保规则如需变更走 DB 修改 + 缓存 TTL 自然过期（_TTL）。
