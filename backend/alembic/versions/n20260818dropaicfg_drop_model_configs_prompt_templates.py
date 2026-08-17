"""删除 model_configs / prompt_templates 表（AI 模型参数与提示词归代码维护）

Revision ID: n20260818dropaicfg
Revises: m20260815hisno
Create Date: 2026-08-18

为什么删：

  这两张表背后是管理后台的「模型配置」「Prompt 管理」两页，2026-08-18 与用户
  商定整体撤掉：
    · 模型配置：只有 DeepSeek 一家两个模型，reasoner 时延不适合医生实时场景；
      温度 / max_tokens 是技术调参项，医院管理员既不懂也不该动，改错直接
      影响病历质量。且「启用」开关是假的——关掉只是回落默认参数，从不拦请求。
    · Prompt 管理：真正读 DB 模板的只有 inquiry / exam 两个场景，其余场景
      早已标注「此处编辑不生效」；提示词属临床安全关键项，与评分标准同理
      应走代码 PR review，不该在后台被无审查地改掉。
  撤页之后表就是"没有任何入口的隐藏配置"，留着只会成为一条看不见的真相源，
  故连表一起删；参数与提示词此后唯一来源是代码
  （app/services/ai/model_options.py、prompts_*.py）。

存量数据（生产 2026-08-18 实测）：
  model_configs   5 行，全部为默认值（deepseek-chat / 0.3 / 4096 / 启用）
  prompt_templates 2 行，均为 generate / polish 场景的种子模板——本就不生效
  即删表后运行行为零变化，无需迁移数据。

幂等：先判表是否存在，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n20260818dropaicfg"
down_revision: Union[str, None] = "m20260815hisno"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("model_configs", "prompt_templates")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table in _TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    """回滚只重建空表结构（按 b20260812squash 基线 DDL）——原数据不恢复。"""
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    if "model_configs" not in existing:
        op.create_table(
            "model_configs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("scene", sa.String(50), nullable=False, unique=True),
            sa.Column("model_name", sa.String(100), nullable=False),
            sa.Column("temperature", sa.Float(), nullable=False),
            sa.Column("max_tokens", sa.Integer(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "prompt_templates" not in existing:
        op.create_table(
            "prompt_templates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("scene", sa.String(50)),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("version", sa.String(20), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
