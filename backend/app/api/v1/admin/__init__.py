"""管理后台路由聚合器（api/v1/admin/__init__.py）

把全部 admin 子路由聚合到一个 APIRouter，统一挂 `audit_admin_action`
依赖——所有管理员特权操作自动审计，新增 admin 模块只需 include 进来
就自动获得审计能力，不会再出现"个别端点忘了写 log_action"。

历史背景：
  之前 v1/__init__.py 是把 9 个 admin/* 模块各自直接 include 到顶层，
  没有聚合层，也没有路由级依赖——审计只能靠人工每个端点写，结果全部漏。
"""
from fastapi import APIRouter, Depends

from app.core.audit_dep import audit_admin_action

from app.api.v1.admin import (
    audit_logs,
    departments,
    model_configs,
    prompts,
    qc_rules,
    records,
    stats,
    users,
    voice_records,
)


# 路由级 dependency：所有挂在本 router 下的 admin 端点自动跑审计 + 角色校验
router = APIRouter(dependencies=[Depends(audit_admin_action)])

router.include_router(users.router, prefix="/users", tags=["管理-用户"])
router.include_router(departments.router, prefix="/departments", tags=["管理-科室"])
router.include_router(qc_rules.router, prefix="/qc-rules", tags=["管理-质控规则"])
router.include_router(prompts.router, prefix="/prompts", tags=["管理-Prompt"])
router.include_router(stats.router, prefix="/stats", tags=["管理-统计"])
router.include_router(records.router, prefix="/records", tags=["管理-病历"])
router.include_router(audit_logs.router, prefix="/audit-logs", tags=["管理-审计日志"])
router.include_router(model_configs.router, prefix="/model-configs", tags=["管理-模型配置"])
router.include_router(voice_records.router, prefix="/voice-records", tags=["管理-语音记录"])
