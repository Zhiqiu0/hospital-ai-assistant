# -*- coding: utf-8 -*-
"""路由树内省（core/route_introspect.py，2026-09-10 依赖升级配套）

为什么存在：fastapi 0.141 / starlette 1.x 改了 include_router 的实现——子路由
不再在 include 时复制展平进 app.routes，而是整棵包在 `_IncludedRouter` 里运行时
组合。两个直接后果，都在升级冒烟里实测到：

  ① `scope["route"]` 变成了**叶子路由**，它的 .path 是相对路径（/search、
     /login），前缀 /api/v1/xxx 只存在于外层 include 的上下文里。访问日志与
     admin 审计的"路由模板"当场退化：request.access 打出 path=/check-username，
     按接口聚合"哪类请求最慢""本月几次病历修订"的能力（#265/#269 刚建立的）
     整个塌掉——不同 router 下同名子路径还会互相混淆。
  ② include 层挂的依赖（admin 聚合 router 上的 audit_admin_action）不再复制进
     叶子的 dependant，鉴权守卫测试摊平叶子依赖会把全部 admin 端点误判成
     "没守卫"；更早一步，路由枚举本身只看 app.routes 的话一条 API 都数不到。

本模块把"递归展开 + 前缀累积 + include 层依赖收集"收在一处，三个消费方共用：
  - RequestIDMiddleware 的访问日志（endpoint → 完整模板）
  - core/audit_dep 的 admin 审计 action
  - tests/test_route_authz_guard 的静态横切

对私有结构（_IncludedRouter / include_context）的依赖集中在这里，且全部
getattr 防御式访问：结构再变时退化为"拿不到前缀就用叶子路径"，行为回到升级前
的已知状态，而 test_observability 的模板聚合用例会立刻转红提醒适配。
"""
from __future__ import annotations

import weakref
from typing import Any, Iterator

# app 实例 -> {endpoint id -> 完整路径模板}。弱引用键：id(app) 作键有 ABA
# 风险（旧 app 回收后新对象可能拿到同一地址，测试里会建多个小 app），
# 弱引用则随 app 回收自动清、天然无此问题。生产进程内 app 是单例，只建一次表。
_template_cache: "weakref.WeakKeyDictionary[Any, dict[int, str]]" = (
    weakref.WeakKeyDictionary()
)


def iter_api_routes(app: Any) -> Iterator[tuple[str, Any, set[str]]]:
    """深度展开路由树，产出 (完整路径模板, 叶子路由, include 层依赖函数名集合)。

    include 层依赖沿途累积：挂在 /api/v1/admin 聚合 router 上的
    audit_admin_action 会出现在其下每一条叶子的集合里。
    """

    def dep_names_of(obj: Any) -> set[str]:
        names: set[str] = set()
        for dep in getattr(obj, "dependencies", None) or []:
            fn = getattr(dep, "dependency", None) or getattr(dep, "call", None)
            if fn is not None:
                names.add(getattr(fn, "__name__", ""))
        return names

    def walk(routes: Any, prefix: str, inherited: set[str]) -> Iterator[tuple[str, Any, set[str]]]:
        for r in routes:
            inner = getattr(r, "original_router", None)
            if inner is not None:  # _IncludedRouter：进下一层
                ctx = getattr(r, "include_context", None)
                sub_prefix = prefix + (getattr(ctx, "prefix", "") or "")
                sub_deps = inherited | dep_names_of(ctx)
                yield from walk(getattr(inner, "routes", []) or [], sub_prefix, sub_deps)
            else:  # 叶子（APIRoute / Route / WebSocketRoute）
                yield prefix + (getattr(r, "path", "") or ""), r, inherited

    yield from walk(getattr(app, "routes", []) or [], "", set())


def full_template_for(scope: dict) -> str | None:
    """按请求 scope 取当前端点的**完整**路径模板；取不到返回 None。

    用 endpoint 函数对象作 key（scope["endpoint"] 与叶子路由的 .endpoint 是
    同一个对象），首个请求时建表并缓存——路由表在启动后不变。
    """
    app = scope.get("app")
    endpoint = scope.get("endpoint")
    if app is None or endpoint is None:
        return None
    table = _template_cache.get(app)
    if table is None:
        table = {}
        for full_path, route, _deps in iter_api_routes(app):
            ep = getattr(route, "endpoint", None)
            if ep is not None:
                table[id(ep)] = full_path
        try:
            _template_cache[app] = table
        except TypeError:
            pass  # app 不可弱引用时放弃缓存，每次现建（正确性不受影响）
    return table.get(id(endpoint))
