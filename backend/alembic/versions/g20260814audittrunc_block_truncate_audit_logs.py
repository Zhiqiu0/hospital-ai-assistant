"""audit_logs 补 TRUNCATE 防护（只追加表的最后一个缺口）

Revision ID: g20260814audittrunc
Revises: f20260813pwdwm
Create Date: 2026-08-14

为什么需要（2026-08-13 第五轮审计发现）：
  基线里的 trg_audit_logs_append_only 是 `BEFORE UPDATE OR DELETE ... FOR EACH ROW`，
  挡得住逐行改删，**挡不住 TRUNCATE**——TRUNCATE 不走行级触发器，一条语句就能
  把整张审计表清空且不留任何痕迹。而放开归属校验后，审计是「谁查阅了谁的病历」
  的唯一追责依据，也是分级评审要查的合规记录。

  PostgreSQL 支持语句级的 BEFORE TRUNCATE 触发器，补上即可堵死这个缺口。
  超级用户仍可先 DROP TRIGGER 再 TRUNCATE——那是数据库账号管理的边界，
  不是应用层能解决的；但这一刀能挡住误操作与常规权限下的清空。

幂等：先 DROP IF EXISTS 再建，重复执行安全（本项目迁移铁律）。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "g20260814audittrunc"
down_revision: Union[str, None] = "f20260813pwdwm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 语句级触发器函数（TG_OP 会是 'TRUNCATE'）
    op.execute("""
        CREATE OR REPLACE FUNCTION audit_logs_block_truncate()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs 是只追加表，禁止 TRUNCATE';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_block_truncate ON audit_logs")
    op.execute("""
        CREATE TRIGGER trg_audit_logs_block_truncate
        BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_block_truncate();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_block_truncate ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_block_truncate()")
