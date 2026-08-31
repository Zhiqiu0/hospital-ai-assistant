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
    doctor_codes,
    patient_merge,
    records,
    rubrics,
    stats,
    users,
    voice_records,
)


# 路由级 dependency：所有挂在本 router 下的 admin 端点自动跑审计 + 角色校验
router = APIRouter(dependencies=[Depends(audit_admin_action)])

router.include_router(users.router, prefix="/users", tags=["管理-用户"])
# HIS 工号绑定管理（2026-09-01）：此前 DoctorCode 只增不改不删，工号绑错人时
# 系统提示"请联系管理员改派"而改派功能并不存在——见 services/doctor_code_service
router.include_router(doctor_codes.router, prefix="/doctor-codes", tags=["管理-HIS工号"])
# 重复档案合并（2026-09-01）：三处代码注释都写着"可事后人工合并"，而合并功能
# 一直不存在——过敏史/既往史分散在两份档案下是临床风险
router.include_router(patient_merge.router, prefix="/patient-merge", tags=["管理-档案合并"])
router.include_router(departments.router, prefix="/departments", tags=["管理-科室"])
# 注：/qc-rules 旧只读端点已删（2026-08-12）——前端 QCRulesPage 早已切到 /rubrics，
# 该端点零调用；qc_rules 表仍被医保规则引擎使用（rule_engine/insurance_rules），表不删。
# 注：/prompts、/model-configs 两组端点已删（2026-08-18）——提示词与模型参数归代码维护，
# 后台不再暴露；对应 prompt_templates / model_configs 表随 alembic 迁移一并删除。
router.include_router(rubrics.router, prefix="/rubrics", tags=["管理-法定评分标准"])
router.include_router(stats.router, prefix="/stats", tags=["管理-统计"])
router.include_router(records.router, prefix="/records", tags=["管理-病历"])
router.include_router(audit_logs.router, prefix="/audit-logs", tags=["管理-审计日志"])
router.include_router(voice_records.router, prefix="/voice-records", tags=["管理-语音记录"])
