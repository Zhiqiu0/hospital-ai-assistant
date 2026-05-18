"""管理后台质控规则接口（/api/v1/admin/qc-rules/*）

L3 治本路线（2026-05-18）：
  浙江省卫健委评分标准是国家法定标准，**不应该让运营在 admin 后台改**。
  评分规则由 qc_engine.rubrics.* 代码常量驱动，PR review + 法律合规复核才能改。

本路由从原来的"完整 CRUD"改为"只读历史日志"：
  - GET /          列出历史规则（兼容老前端的查看页面）
  - 其他 405       创建/更新/删除/启停全部禁用

为什么不直接删除整个端点：
  保留 GET 兼容前端 QCRulesPage 的"评分标准查看"功能（虽然展示的是 DB 旧数据
  而非新的 Rubric，下一步前端切到 GET /rubric/{name} 暴露法定标准），避免一次
  砍掉太多导致前端报 404。下一期前端切完后整个端点删除。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.database import get_db
from app.models.config import QCRule
from app.schemas.config import QCRuleResponse

router = APIRouter()


# ─── 仅保留只读列表 ──────────────────────────────────────────────────


@router.get("", response_model=dict)
async def list_rules(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """列出历史质控规则（只读）。

    新评分标准走 qc_engine.rubrics 代码常量，本接口仅返回 DB 历史规则供查看，
    不再用于在线评分。前端 QCRulesPage 切到展示新 Rubric 后此接口可删除。
    """
    result = await db.execute(select(QCRule).order_by(QCRule.rule_code))
    items = result.scalars().all()
    return {"items": [QCRuleResponse.model_validate(item) for item in items]}


# ─── 写入端点全部 410 Gone（治本：法定标准不应在线编辑） ────────────


def _read_only_response() -> HTTPException:
    """统一的"只读"响应——410 Gone 比 403 Forbidden 语义更准。

    410 表示资源永久不可用（不是权限问题，是该功能已下线），
    前端收到后应提示用户"评分标准已迁移到代码常量，请联系开发"。
    """
    return HTTPException(
        status_code=410,
        detail=(
            "评分规则已改为法定标准代码常量，admin 后台不再支持在线编辑。"
            "如需调整请联系开发团队（走 PR review + 法律合规复核）。"
        ),
    )


@router.post("", status_code=410)
async def create_rule_disabled(_=Depends(require_admin)):
    raise _read_only_response()


@router.put("/{rule_id}", status_code=410)
async def update_rule_disabled(rule_id: str, _=Depends(require_admin)):  # noqa: ARG001
    raise _read_only_response()


@router.put("/{rule_id}/toggle", status_code=410)
async def toggle_rule_disabled(rule_id: str, _=Depends(require_admin)):  # noqa: ARG001
    raise _read_only_response()


@router.delete("/{rule_id}", status_code=410)
async def delete_rule_disabled(rule_id: str, _=Depends(require_admin)):  # noqa: ARG001
    raise _read_only_response()
