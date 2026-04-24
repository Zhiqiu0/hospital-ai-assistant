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
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import router as api_v1_router
from app.config import settings
from app.core.logging_config import setup_logging
from app.database import AsyncSessionLocal
from app.schema_compat import apply_schema_compatibility

# 初始化日志：级别从 settings 读取（默认 INFO），格式由 setup_logging 统一配置
setup_logging(log_level=getattr(settings, "log_level", "INFO"))
logger = logging.getLogger(__name__)

# ── FastAPI 实例 ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="MediScribe 临床接诊智能助手",
    description="医院临床接诊智能助手系统 API",
    version="1.0.0",
    docs_url="/docs",      # Swagger UI，仅开发环境开放
    redoc_url="/redoc",    # ReDoc 文档
)

# ── CORS 跨域中间件 ────────────────────────────────────────────────────────────
# allowed_origins 从 settings 读取（支持逗号分隔多域名），生产环境需精确配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,  # 允许的前端域名列表
    allow_credentials=True,               # 允许携带 Cookie/Authorization
    allow_methods=["*"],                  # 允许所有 HTTP 方法
    allow_headers=["*"],                  # 允许所有请求头
)

# ── 路由挂载 ──────────────────────────────────────────────────────────────────
# 所有业务 API 均挂载在 /api/v1 前缀下
app.include_router(api_v1_router, prefix="/api/v1")


# ── 全局异常处理器 ────────────────────────────────────────────────────────────
# 未被路由层捕获的异常（500 Internal Server Error）会落到这里。
# 默认 FastAPI 只返 500 不记录堆栈——排查 bug 时一筹莫展。
# 这里把完整 traceback 写入 error.log，并给前端一个清晰的 detail（不泄露内部细节）。
@app.exception_handler(Exception)
async def catch_all_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.error(
        "Unhandled exception on %s %s: %s: %s\n%s",
        request.method,
        request.url.path,
        type(exc).__name__,
        str(exc)[:200],
        tb,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务器内部错误，请稍后重试（技术细节已记录到服务端日志）",
            "error_type": type(exc).__name__,
        },
    )


# ── 生命周期钩子 ──────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """应用启动时执行：
    1. 打印启动日志
    2. 执行 schema_compat 兼容性检查（自动为旧版 DB 补充缺失字段）
    """
    logger.info("MedAssist 后端启动")
    await apply_schema_compatibility()


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
    except Exception as e:
        logger.error("Health check: DB unreachable: %s", e)
        db_status = "error"

    status = "ok" if db_status == "ok" else "degraded"
    return {"status": status, "db": db_status, "version": "1.0.0"}
