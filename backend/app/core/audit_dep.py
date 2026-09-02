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
  admin:METHOD:<路由模板>
  示例：admin:POST:/api/v1/admin/users              → 创建用户
        admin:DELETE:/api/v1/admin/users/{user_id}  → 停用某用户

  **必须用路由模板而不是实际路径**（2026-09-02 审计日志专项修正）：原实现取
  request.url.path，把资源 UUID 写进了 action 里——生产上 281 条 admin 审计
  产生了 34 种 action 取值，每停用一个账号、每修订一份病历都新增一种，而
  resource_id 列反倒全空（填充率 0/281）。
  后果是审计日志最基本的用途当场失效：想查"本月发生过几次病历修订"，
  GROUP BY action 得到的是一堆各不相同的 URL；按操作类型建索引也无意义。
  路由模板收敛成稳定的十几种，实际资源 ID 放进它该在的 resource_id 列，
  两个维度都能查。
"""
from fastapi import Depends, Request

from app.core.client_ip import get_client_ip
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
        # 路由模板（/api/v1/admin/users/{user_id}）而不是实际路径——理由见模块
        # 头部的命名约定。取不到 route 时（理论上不会）退回实际路径，宁可粒度
        # 粗一点也不能丢审计。query string 一律不入，避免泄露搜索关键字这类
        # 可读 PII。
        route = request.scope.get("route")
        action_path = getattr(route, "path", None) or request.url.path
        # 实际资源 ID 归位到 resource_id 列：路径参数通常只有一个（user_id /
        # code / rubric_key…），多个时拼起来，保证可追溯到具体对象
        params = request.path_params or {}
        resource_id = "/".join(str(v) for v in params.values()) or None
        await log_action(
            action=f"admin:{request.method}:{action_path}",
            user_id=current_user.id,
            user_name=current_user.username,
            user_role=current_user.role,
            resource_id=resource_id,
            ip_address=get_client_ip(request),
            status=status,
        )
