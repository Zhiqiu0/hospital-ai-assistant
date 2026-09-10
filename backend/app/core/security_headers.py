"""安全响应头中间件（core/security_headers.py）

2026-06-11 安全审计加固：为所有响应补充浏览器级防护头。
医疗系统受等保 2.0 三级约束，错误配置的浏览器防护是审计扣分项。

各响应头作用：
  - X-Content-Type-Options: nosniff   禁止浏览器 MIME 嗅探，防止把 JSON 当脚本执行
  - X-Frame-Options: DENY             禁止被 iframe 嵌套，防点击劫持
  - Referrer-Policy                   跨站跳转不带来源路径，防 URL 中的 ID 泄露
  - Strict-Transport-Security         强制 HTTPS（仅生产域名走 HTTPS 时生效，本地无副作用）
  - Content-Security-Policy           API 响应禁止一切资源加载；/docs /redoc 例外
                                      （Swagger UI 需要加载 CDN 脚本，设了会白屏）
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


# Swagger/ReDoc 文档页需要外部脚本，跳过 CSP（其余安全头仍然生效）
_CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """给每个响应追加安全头；纯写 header，无业务逻辑，开销可忽略。"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        if not request.url.path.startswith(_CSP_EXEMPT_PREFIXES):
            # API 只返回 JSON，禁止一切资源加载是最严格且无副作用的配置
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'")
        # PHI 响应禁缓存（2026-09-10 第 20 轮 HTTP 缓存面审计）：此前 API 的
        # JSON 响应没有任何 Cache-Control——患者列表/工作台快照这类含 PHI 的
        # 响应可能被写进浏览器磁盘缓存，而"共用诊室电脑"正是本系统的威胁
        # 模型（登出清 localStorage 防的就是它，HTTP 缓存这条路此前漏了）。
        # setdefault 语义：已显式声明缓存策略的端点不动（如影像帧的
        # private+max-age，是刻意的性能取舍且图像走带鉴权代理）。
        response.headers.setdefault("Cache-Control", "no-store")
        return response
