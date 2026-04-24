"""管理员路由审计依赖（core/audit_dep.py）

为什么需要：
  历史上 admin/* 路由（用户增删、改 Prompt、改质控规则、删患者等）
  全部依赖人工在每个端点写 `await log_action(...)`——结果就是 9 个 admin
  模块 0 调用，所有管理员特权操作零审计。这是合规级别的硬伤。

设计思路：
  把审计变成路由级 dependency，挂在 admin 子路由聚合器上一次，所有
  admin 路径自动覆盖；新增 admin 模块只要挂进 admin 聚合 router 就
  自动获得审计能力，不会再有"忘了写"的可能。

行为：
  - 复用 require_admin 做角色校验（依赖图自动缓存，不会重复跑）
  - 用 yield-style 依赖捕获请求成功/失败两种路径，都写一条 audit 日志
  - 通过 audit_service.log_action 独立 session 写库，不阻塞主流程事务

action 命名约定：
  admin:METHOD:/api/v1/admin/xxx
  示例：admin:POST:/api/v1/admin/users  → 创建用户
        admin:DELETE:/api/v1/admin/users/abc  → 停用某用户
"""
from fastapi import Depends, Request

from app.core.security import require_admin
from app.services.audit_service import log_action


async def audit_admin_action(
    request: Request,
    current_user=Depends(require_admin),
):
    """admin 路由级审计依赖。

    yield 之前：require_admin 已确认当前是管理员且 token 有效。
    yield 之后：无论端点成功 / 抛异常，都记一条 audit 日志，区分 status。
    """
    status = "ok"
    try:
        yield current_user
    except Exception:
        # 端点失败也要审计（管理员"尝试做某事但失败"同样是合规事件）
        status = "fail"
        raise
    finally:
        # 路径里去掉 query string，避免泄露搜索关键字之类的可读 PII
        path = request.url.path
        await log_action(
            action=f"admin:{request.method}:{path}",
            user_id=current_user.id,
            user_name=current_user.username,
            user_role=current_user.role,
            ip_address=request.client.host if request.client else None,
            status=status,
        )
