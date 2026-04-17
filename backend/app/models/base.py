"""
ORM 基础工具（models/base.py）

提供两个全局复用组件：
  - TimestampMixin : 为 ORM Model 自动注入 created_at / updated_at 两个时间戳字段
  - generate_uuid  : 生成随机 UUID 字符串，用作主键默认值

设计说明：
  所有需要时间戳的 Model 都应混入 TimestampMixin，如：
    class MyModel(Base, TimestampMixin):
        ...

  主键使用 UUID 而非自增整数，原因：
    1. 前端/后端可以在不访问数据库的情况下提前生成 ID
    2. 分布式场景下无冲突风险
    3. 避免 ID 连续性导致的 IDOR（不安全直接对象引用）漏洞
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """为 ORM Model 提供 created_at 和 updated_at 时间戳字段。

    created_at: 记录创建时间，由数据库 func.now() 自动填充，不会更新。
    updated_at: 记录最后修改时间，每次 UPDATE 时由 SQLAlchemy onupdate 自动刷新。

    使用方式：
        class MyModel(Base, TimestampMixin):
            __tablename__ = "my_table"
            id: Mapped[str] = mapped_column(...)
    """

    # 创建时间：INSERT 时由数据库 now() 填充，之后不再变更
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    # 更新时间：INSERT 时设为 now()，每次 UPDATE 时自动更新为当前时间
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


def generate_uuid() -> str:
    """生成随机 UUID4 字符串，用作数据库主键默认值。

    Returns:
        形如 "550e8400-e29b-41d4-a716-446655440000" 的 UUID 字符串。

    使用方式：
        id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    """
    return str(uuid.uuid4())
