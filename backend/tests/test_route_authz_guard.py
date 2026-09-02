# -*- coding: utf-8 -*-
"""路由鉴权守卫的静态横切（2026-09-03 新增）。

单个端点的权限边界各处都测过了，但没人守着**新加的端点有没有忘记挂守卫**——
而那正是权限漏洞最常见的来源：写业务逻辑时想着功能，鉴权依赖漏一行，代码评审
也未必看得出来，直到 PHI 被越权读走。

本文件枚举 FastAPI 的全部路由，要求 /api/v1 下每一条都能在依赖链里找到鉴权，
例外必须显式登记在下面的白名单里并写清替代防护是什么。新加一个裸端点，这里
就会红。

首次跑的结论：9 条例外全部合理（逐条实测/审阅过），登记如下。
"""
from app.main import app

# 依赖链里出现任一个即视为"有鉴权"
_AUTH_DEPS = {
    "get_current_user",       # 常规登录态
    "require_admin",          # 管理员
    "audit_admin_action",     # admin 路由级依赖（内含 require_admin）
    "require_his_enabled",    # HIS 保险丝 + 端点内验签
    "_oauth2",                # 只取自己的 token（logout）
}

# 公开端点白名单：key 是路径，value 是"为什么可以公开 + 替代防护是什么"。
# 加条目前先问：这条真的必须公开吗？替代防护实测过吗？
_PUBLIC_ALLOWED = {
    "/api/v1/auth/login":
        "登录入口本身；按用户名限速防单账号爆破",
    "/api/v1/auth/logout":
        "只吊销请求方自己的 token，无 token 时幂等返回 200",
    "/api/v1/auth/check-username":
        "建号前查重；按 IP 限速 20 次/分——用户名即工号（院内公开），"
        "无限速可被脚本枚举全院账号再定向爆破",
    "/api/v1/health":
        "容器 liveness 与 uptime-kuma 探活",
    "/api/v1/health/deep":
        "依赖深度检查；只回组件状态与版本，不含内部细节",
    "/api/v1/sentry-tunnel":
        "前端异常上报代理（SDK 内部 fetch 不带 Authorization，加 auth 会让登录页"
        "的报错上报不上去）。四道护栏：DSN 白名单防 SSRF / body 100KB / 每 IP "
        "10 次每秒 / 5s 超时",
    "/api/v1/ai/voice-records/{voice_record_id}/audio":
        "HTML <audio> 无法带请求头，改用一次性音频令牌（5 分钟、独立 audience、"
        "绑定该条录音）。已实测：会话令牌 401、跨资源 403、伪造 401、缺令牌 422",
    "/api/v1/ai/voice-stream":
        "WebSocket，握手后在处理函数内校验令牌（依赖注入拿不到 WS 的 header）",
    "/api/v1/his/ws":
        "HIS 长连接，函数内做 HMAC 验签 + 时间戳 + nonce 防重放",
}


def _dependency_names(route) -> set[str]:
    """把一条路由的依赖链摊平成函数名集合。"""
    names: set[str] = set()
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return names
    stack = [dependant]
    while stack:
        cur = stack.pop()
        fn = getattr(cur, "call", None)
        if fn is not None:
            names.add(getattr(fn, "__name__", ""))
        stack.extend(getattr(cur, "dependencies", None) or [])
    return names


def _api_routes():
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/api/v1"):
            yield r, path


def test_没有未登记的裸端点():
    """新加的 /api/v1 端点必须挂鉴权，或显式登记为公开并说明替代防护。"""
    naked = [
        f"{','.join(sorted(getattr(r, 'methods', None) or []))} {p}"
        for r, p in _api_routes()
        if not (_dependency_names(r) & _AUTH_DEPS) and p not in _PUBLIC_ALLOWED
    ]
    assert not naked, (
        "以下端点既没有鉴权依赖，也没有登记进公开白名单：\n  "
        + "\n  ".join(naked)
        + "\n若确实该公开，请在 _PUBLIC_ALLOWED 里写清替代防护是什么。"
    )


def test_白名单不留过期条目():
    """端点被删/改名后，白名单条目要跟着清掉，否则会悄悄放行一个新的同名路径。"""
    existing = {p for _, p in _api_routes()}
    stale = sorted(set(_PUBLIC_ALLOWED) - existing)
    assert not stale, f"白名单里这些路径已不存在，请删除：{stale}"


def test_管理端点一律走管理员守卫():
    """/api/v1/admin/* 是全院数据的写入口，一条都不能漏。"""
    bad = [
        p for r, p in _api_routes()
        if p.startswith("/api/v1/admin")
        and not (_dependency_names(r) & {"require_admin", "audit_admin_action"})
    ]
    assert not bad, f"这些管理端点没有管理员守卫：{bad}"


def test_管理端点一律留审计():
    """管理员特权操作必须留痕——历史上 9 个 admin 模块 0 调用 log_action，
    正是为此才有了路由级的 audit_admin_action 依赖。"""
    bad = [
        p for r, p in _api_routes()
        if p.startswith("/api/v1/admin")
        and "audit_admin_action" not in _dependency_names(r)
    ]
    assert not bad, f"这些管理端点不会被审计：{bad}"
