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

from datetime import datetime
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
# 注：原启动期 schema 兼容检查（schema_compat）已随迁移收口删除（2026-08-12）——
# 表结构统一由 alembic 在 entrypoint 阶段维护，应用启动不再执行任何 DDL
# （顺带消除了 2 worker 并发跑 create_all 的竞态）。
@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("app.startup: ok")
    # HIS 回写指令消费任务（2026-08-11 业务联动）：多 worker 部署下，签发请求
    # 与厂商 WS 连接可能不在同一进程，回写指令经 Redis 总线广播、由持有连接的
    # worker 抢占执行。保险丝关闭时不起任务，生产 SaaS 零影响。
    # 回写对账任务（2026-08-11 病历安全）：周期扫"已签发但回写未成功"的 HIS 接诊
    # 自动重投，耗尽报 Sentry。多 worker 靠 Redis 锁防重。同受保险丝保护。
    # 回收被上一次进程退出打断的检验单解析（2026-08-14 第八轮审计）：
    # OCR 是「先落 analyzing → 最长 3 分钟外部调用 → 再落 done」，deploy 重启
    # 必然会打断其中一些，那些记录永久停在 analyzing、ocr_text 为空，医生看到
    # 一张空卡片却既不知道失败也无法重来。启动时扫一次正好收拾上一次的残局。
    # 失败不阻断启动——它只是收尾工作，不值得让整个服务起不来。
    try:
        from app.database import AsyncSessionLocal
        from app.services.lab_reports_service import reclaim_stale_analyzing
        async with AsyncSessionLocal() as _db:
            await reclaim_stale_analyzing(_db)
    except Exception as exc:
        logger.warning("app.startup: 回收卡死的检验单解析失败 err=%s", exc)

    bg_tasks = []
    import asyncio
    if settings.his_adapter_enabled:
        from app.his_adapter.writeback_dispatch import consumer_loop
        from app.his_adapter.writeback_reconcile import reconcile_loop
        bg_tasks.append(asyncio.create_task(consumer_loop()))
        bg_tasks.append(asyncio.create_task(reconcile_loop()))
    # AI 余额预警（2026-08-16 上线前体检）：余额耗尽是全院级单点——所有医生的
    # 所有 AI 功能同时停摆且毫无前兆（体检当天实测余额仅够约 130 次接诊）。
    # 只在配了 key 时起；查询失败静默降级，不影响主流程。
    if settings.deepseek_api_key:
        from app.services.ai.balance_monitor import balance_monitor_loop
        bg_tasks.append(asyncio.create_task(balance_monitor_loop()))
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
@app.get("/api/v1/health/deep")
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

    # AI 凭证（2026-08-13 第二轮审计修复）：DEEPSEEK_API_KEY 缺失时应用照常启动、
    # 容器健康检查照常绿、部署报成功，但病历生成/质控/建议全部报错——"看着健康
    # 实则核心功能全废"。凭证是启动即可判定的静态配置，纳入深度健康检查。
    # 不做真实 LLM 调用（会拖慢监控探测并烧 token），只查凭证是否配齐。
    deps["ai_credential"] = "ok" if settings.deepseek_api_key else "missing"

    # Orthanc / PACS 影像服务器（2026-09-01 可观测性审计）：
    # orthanc_client.health_check() 早就写好了，却**只在手工冒烟脚本里被调用过**，
    # 从未接进任何自动探活。于是 Orthanc 容器挂掉时：uptime-kuma（只测前端+API）
    # 绿、/health/deep 绿，而全院影像上传/查看已经失效——医生看到的只是泛化的
    # "服务器内部错误，请稍后重试"，运维只能等人投诉才知道，期间可能已经数小时。
    # 与 db/redis/ai_credential 同口径纳入关键依赖。
    try:
        from app.services.orthanc_client import orthanc_client
        deps["orthanc"] = "ok" if await orthanc_client.health_check() else "error"
    except Exception as exc:
        logger.error("health.deep.orthanc: failed err=%s", exc)
        deps["orthanc"] = "error"

    # 节假日日历覆盖（2026-08-31 跨年边界审计）：与 ai_credential 同一类问题——
    # 日历过期后系统照常跑、健康检查照常绿，但「7 个工作日内归档」这类**法定
    # 时限**会把节假日当工作日算，医务科对外通报的质控指标随之失真。这是启动
    # 即可判定的静态配置，纳入深度检查；expiring 只提示（运维有 60 天余量去查
    # 国办发布的次年安排），expired 才算关键故障。
    from app.services.workdays import calendar_status
    _cal, _days_left = calendar_status()
    deps["holiday_calendar"] = (
        _cal if _cal != "ok" else f"ok（覆盖至年末，剩 {_days_left} 天）"
    )

    # 数据库时钟与应用时钟的偏差（2026-09-02 时间口径审计）。
    #
    # 本系统里两种时钟源并存：created_at / recorded_at / completed_at 由数据库端
    # func.now() 生成，visited_at / submitted_at 由应用进程 datetime.now() 生成，
    # 而好几处法定判定要拿这两类值直接相减：
    #   · 补记标识    is_late_entry(recorded_at, created_at)
    #   · 补记判据②  recorded_at > completed_at（出院后才落笔）
    #   · 时效达标率  submitted_at - completed_at（出院记录 24h）
    #   · 文书倒计时  now() - completed_at
    # 两边对齐靠的是「PG 连接设了 timezone=Asia/Shanghai（database.py）+ 应用
    # 容器 TZ 也是北京时间」这一配置前提。前提一旦漂了，系统照常跑、日志无痕，
    # 但补记会整片漏标、出院记录时效达标率会整体偏 8 小时——而这些数字要拿去
    # 考核医生。让它可发现，好过等医务科拿着通报来问。
    # 判据取 5 秒：正常网络往返远小于它；越过说明是时区或 NTP 层面的问题。
    clock_skew = None
    try:
        from sqlalchemy import text as _text

        from app.database import engine as _engine
        async with _engine.connect() as _c:
            # 必须是 now()::timestamp 而不是裸 now()（2026-09-02 自查修正）：
            # now() 返回 timestamptz，asyncpg 给回的是 **UTC** 时区的 aware
            # datetime，直接砍掉 tzinfo 会稳定报出 8 小时假偏差。而落库到
            # DateTime（无时区）列时，PG 是按连接 timezone 转成本地 naive 再存
            # ——`::timestamp` 走的正是这条转换，与 created_at 的落库值同一口径，
            # 也正是这里要比的那个东西。（探针写错会天天喊狼来了，比不查更糟。）
            _db_now = (await _c.execute(_text("SELECT now()::timestamp"))).scalar()
        if _db_now is not None:
            clock_skew = abs((datetime.now() - _db_now).total_seconds())
            deps["clock_skew"] = (
                f"ok（{clock_skew:.1f}s）" if clock_skew <= 5
                else f"skewed（应用与数据库时钟相差 {clock_skew:.0f} 秒，"
                     f"补记标识与时效达标率会失真）"
            )
    except Exception as exc:
        deps["clock_skew"] = f"error: {type(exc).__name__}"

    critical_down = (
        deps.get("db") == "error"
        or deps.get("redis") == "error"
        or deps.get("ai_credential") == "missing"
        or deps.get("orthanc") == "error"
        or _cal == "expired"
    )
    body = {
        "status": "degraded" if critical_down else "ok",
        "deps": deps,
        "version": "1.0.0",
    }
    # 关键依赖挂 → 503 让 uptime-kuma 告警；否则 200
    return JSONResponse(status_code=503 if critical_down else 200, content=body)
