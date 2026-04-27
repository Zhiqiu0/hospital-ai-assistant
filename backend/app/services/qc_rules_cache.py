"""QC 规则 Redis 缓存层（services/qc_rules_cache.py）

规则引擎每次质控都查 qc_rules 表（按 rule_type + is_active 过滤），
完整性规则和医保规则共用本模块。

设计：
  - 把 ORM 序列化为 dict 写 Redis
  - 读取时还原成 SimpleNamespace，让规则引擎用属性访问保持无感知
  - admin 写 qc_rules（创建/更新/切换/删除）后调 invalidate_qc_rules() 主动失效
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional

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


async def invalidate_qc_rules(rule_type: Optional[str] = None) -> None:
    """admin 写 qc_rules 后调，让所有进程立即看到新规则。

    Args:
        rule_type: 指定类型失效；传 None 失效所有类型。
    """
    if rule_type:
        await redis_cache.delete(_KEY.format(rule_type=rule_type))
    else:
        await redis_cache.delete_prefix("qc:rules:")
