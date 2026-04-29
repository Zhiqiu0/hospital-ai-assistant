"""clean_orphan_ai_tasks

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-04-30 00:00:00.000000

变更内容：
  清理 ai_tasks / qc_issues 表里的"孤儿数据"——
  历史上 log_ai_task 函数从未接收 encounter_id 参数，导致所有 AI 任务记录的
  encounter_id 都是 NULL。无法按"哪次接诊"反查，等于审计断链。

  本轮治本（RequestContext middleware + bind_encounter_context）补全了
  encounter_id 写入路径。存量孤儿数据无法补救（不知道属于哪个接诊），
  按用户决策直接清掉，避免误导审计/统计。

清理策略：
  1. 先 DELETE qc_issues：所有指向"encounter_id 为 NULL 的 ai_task"的 issue
     —— 没法关联到接诊的质控记录留着也没用
  2. 再 DELETE ai_tasks WHERE encounter_id IS NULL
  3. **不加 NOT NULL 约束**：AITask 模型设计允许 encounter_id NULL
     （后台批量任务 / 管理工具调用 等场景），仅业务路径要求非空，
     由 RequestContext + 路由层负责保证。

回滚：downgrade 不做任何事——孤儿数据无法重建（信息已经丢失）。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 清孤儿 qc_issues（先删子表，避免外键约束 / 减少后续 DELETE 工作量）
    op.execute(
        """
        DELETE FROM qc_issues
        WHERE ai_task_id IN (
            SELECT id FROM ai_tasks WHERE encounter_id IS NULL
        )
        """
    )
    # 2. 清孤儿 ai_tasks
    op.execute("DELETE FROM ai_tasks WHERE encounter_id IS NULL")


def downgrade() -> None:
    # 数据已丢失，无法恢复——保持 no-op
    pass
