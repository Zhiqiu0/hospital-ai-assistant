"""
住院专项 API 路由聚合（api/v1/inpatient.py）

Round 5 瘦身：原文件 323 行超标，按职责拆到同目录子模块（各自建 router，本文件聚合）——
  inpatient_vitals      : POST/GET /encounters/{id}/vitals、GET .../vitals/latest（生命体征）
  inpatient_problems    : POST/GET/PATCH/DELETE /encounters/{id}/problems（问题列表）
  inpatient_compliance  : GET /encounters/{id}/compliance（时效合规）
本文件保留主 router，直接挂载「病区视图」入口并 include 三个子路由
（路径/方法/依赖零改动，行为完全一致）。

端点列表：
  GET    /inpatient/ward                         - 病区视图：当前医生的活跃住院接诊列表
  POST   /encounters/{id}/vitals                 - 录入生命体征
  GET    /encounters/{id}/vitals                 - 获取体征历史
  GET    /encounters/{id}/vitals/latest          - 获取最新一次体征
  POST   /encounters/{id}/problems               - 新增问题/诊断
  GET    /encounters/{id}/problems               - 获取问题列表
  PATCH  /encounters/{id}/problems/{pid}         - 更新问题状态
  DELETE /encounters/{id}/problems/{pid}         - 删除问题
  GET    /encounters/{id}/compliance             - 时效合规检查
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.services import inpatient_service

# 同目录子路由（各自持有 APIRouter，端点路径与拆分前逐字一致）
from app.api.v1 import inpatient_compliance, inpatient_problems, inpatient_vitals

# 主 router：仍由 app/api/v1/__init__.py 以 prefix="" 注册；
# 子路由不带额外 prefix，拼回后端点路径与原文件完全相同。
router = APIRouter()


# ── 病区视图 ──────────────────────────────────────────────────────────────────

@router.get("/inpatient/ward")
async def get_ward_view(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """返回当前医生负责的活跃住院接诊列表（用于病区视图）。"""
    items = await inpatient_service.list_active_ward(db, current_user.id)
    return {"items": items}


router.include_router(inpatient_vitals.router)
router.include_router(inpatient_problems.router)
router.include_router(inpatient_compliance.router)
