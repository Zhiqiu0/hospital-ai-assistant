"""
FastAPI 应用入口（main.py）

职责：
  - 创建 FastAPI 实例并配置元信息（标题、版本、文档路径）
  - 注册 CORS 跨域中间件（允许前端开发服务器访问）
  - 挂载 /api/v1 路由组
  - 应用启动时执行数据库 schema 兼容性检查
  - 提供 /health 健康检查端点（同时验证 DB 连通性）

部署说明：
  容器内通过 uvicorn app.main:app 启动，健康检查端点由 Docker/K8s 探活使用。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import router as api_v1_router
from app.config import settings
from app.core.logging_config import setup_logging
from app.core.request_context import RequestIDMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.sentry_init import init_sentry
from app.database import AsyncSessionLocal
from app.schema_compat import apply_schema_compatibility

# 初始化日志：级别从 settings 读取（默认 INFO），格式由 setup_logging 统一配置
setup_logging(log_level=getattr(settings, "log_level", "INFO"))
logger = logging.getLogger(__name__)

# 初始化 Sentry：DSN 留空则跳过（本地开发默认不上报）
# 必须在 FastAPI 实例创建前调用，否则 FastApiIntegration 不会自动挂中间件
# release 由 CI deploy 注入 git SHA，本地开发留空（event 无 release tag）
init_sentry(
    dsn=settings.sentry_dsn,
    environment=settings.sentry_environment or settings.app_env,
    traces_sample_rate=settings.sentry_traces_sample_rate,
    release=settings.sentry_release or None,
)

# ── 生命周期（lifespan）──────────────────────────────────────────────────────
# 2026-06-11：替换弃用的 @app.on_event("startup")，行为不变：
# 启动时打日志 + 执行 schema 兼容性检查（自动为旧版 DB 补缺失字段）
@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("app.startup: ok")
    await apply_schema_compatibility()
    # HIS 回写指令消费任务（2026-08-11 业务联动）：多 worker 部署下，签发请求
    # 与厂商 WS 连接可能不在同一进程，回写指令经 Redis 总线广播、由持有连接的
    # worker 抢占执行。保险丝关闭时不起任务，生产 SaaS 零影响。
    # 回写对账任务（2026-08-11 病历安全）：周期扫"已签发但回写未成功"的 HIS 接诊
    # 自动重投，耗尽报 Sentry。多 worker 靠 Redis 锁防重。同受保险丝保护。
    bg_tasks = []
    if settings.his_adapter_enabled:
        import asyncio
        from app.his_adapter.writeback_dispatch import consumer_loop
        from app.his_adapter.writeback_reconcile import reconcile_loop
        bg_tasks.append(asyncio.create_task(consumer_loop()))
        bg_tasks.append(asyncio.create_task(reconcile_loop()))
    yield
    for t in bg_tasks:
        t.cancel()


# ── FastAPI 实例 ──────────────────────────────────────────────────────────────
# API 文档仅非生产环境暴露（2026-08-11 审计修复）：生产开放 /docs /redoc /openapi.json
# 等于把全部端点结构、参数、schema 公开给公网扫描器，与原注释"仅开发环境开放"矛盾。
# 生产（app_env=production）一律关闭，其余环境保留便于联调。
_docs_enabled = settings.app_env != "production"
app = FastAPI(
    title="MediScribe 临床接诊智能助手",
    description="医院临床接诊智能助手系统 API",
    version="1.0.0",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    lifespan=lifespan,
)

# ── 请求 ID 中间件 ─────────────────────────────────────────────────────────────
# 给每个请求生成短 UUID 注入 contextvar，让所有日志能 grep "rid=xxx" 串成链。
# 注意：必须在 CORSMiddleware 之前 add（Starlette 中间件后注册先执行），
# 这样 OPTIONS 预检请求也会带上 request_id，前端报错截图能直接定位。
app.add_middleware(RequestIDMiddleware)

# ── CORS 跨域中间件 ────────────────────────────────────────────────────────────
# allowed_origins 从 settings 读取（支持逗号分隔多域名），生产环境需精确配置
# 2026-06-11 安全加固：方法/请求头从通配收窄为实际使用的白名单（等保审计项）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,  # 允许的前端域名列表
    allow_credentials=True,               # 允许携带 Cookie/Authorization
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],      # 让前端报错时能读到请求 ID 用于排查
    max_age=3600,                         # 预检结果缓存 1h，减少 OPTIONS 请求
)

# ── 安全响应头中间件 ───────────────────────────────────────────────────────────
app.add_middleware(SecurityHeadersMiddleware)

# ── 路由挂载 ──────────────────────────────────────────────────────────────────
# 所有业务 API 均挂载在 /api/v1 前缀下
app.include_router(api_v1_router, prefix="/api/v1")


# ── 全局异常处理器 ────────────────────────────────────────────────────────────
# 未被路由层捕获的异常（500 Internal Server Error）会落到这里。
# logger.exception 写堆栈到 error.log；Sentry LoggingIntegration 会自动转成 event。
# 不再手工 traceback.format_exc()——SDK 自带堆栈采集，避免双写。
@app.exception_handler(Exception)
async def catch_all_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "app.unhandled_exception: method=%s path=%s type=%s",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    # 2026-06-11 安全加固：不再返回 error_type——内部异常类型名暴露实现细节
    # （等保 2.0 三级要求错误消息不含系统内部信息），细节只进日志/Sentry
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误，请稍后重试（技术细节已记录到服务端日志）",
        },
    )


# ── 健康检查 ──────────────────────────────────────────────────────────────────

@app.get("/health")
@app.get("/api/v1/health")
async def health_check():
    """健康检查端点——同时验证数据库连通性，供 CI/CD 部署后探活使用。

    返回格式：
      { "status": "ok"|"degraded", "db": "ok"|"error", "version": "1.0.0" }

    status 为 "degraded" 表示服务进程正常但数据库不可达。
    """
    try:
        # 执行最简单的 DB 查询验证连通性（不操作业务表）
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        logger.error("health.db: failed err=%s", exc)
        db_status = "error"

    status = "ok" if db_status == "ok" else "degraded"
    return {"status": status, "db": db_status, "version": "1.0.0"}


@app.get("/health/deep")
async def health_check_deep():
    """深度健康检查（2026-08-11 病历安全）：除 DB 外并发探活 Redis。

    为什么单独一个端点：容器 liveness 用 /api/v1/health（只看 DB，避免 Redis 抖动
    误触发容器重启）；本端点给 uptime-kuma 监控用——Redis 是多 worker 下 HIS 病历
    回写的事件总线，它挂了主 /health 照样绿、回写却静默停摆。任一关键依赖不可用返
    503，让外部监控立即告警，不再"看着健康实则半瘫"。
    """
    from fastapi.responses import JSONResponse

    deps: dict[str, str] = {}
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        deps["db"] = "ok"
    except Exception as exc:
        logger.error("health.deep.db: failed err=%s", exc)
        deps["db"] = "error"

    # Redis：HIS 回写总线 + 缓存。用 redis_cache 单例的底层 client ping。
    try:
        from app.services.redis_cache import redis_cache
        client = redis_cache._get_client()  # 未配置返回 None
        if client is None:
            deps["redis"] = "unconfigured"
        else:
            await client.ping()
            deps["redis"] = "ok"
    except Exception as exc:
        logger.error("health.deep.redis: failed err=%s", exc)
        deps["redis"] = "error"

    critical_down = deps.get("db") == "error" or deps.get("redis") == "error"
    body = {
        "status": "degraded" if critical_down else "ok",
        "deps": deps,
        "version": "1.0.0",
    }
    # 关键依赖挂 → 503 让 uptime-kuma 告警；否则 200
    return JSONResponse(status_code=503 if critical_down else 200, content=body)
