import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.config import settings
from app.api.v1 import router as api_v1_router
from app.schema_compat import apply_schema_compatibility
from app.core.logging_config import setup_logging
from app.database import AsyncSessionLocal

setup_logging(log_level=getattr(settings, "log_level", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(
    title="MediScribe 临床接诊智能助手",
    description="医院临床接诊智能助手系统 API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_v1_router, prefix="/api/v1")


@app.on_event("startup")
async def startup_event():
    logger.info("MedAssist 后端启动")
    await apply_schema_compatibility()


@app.get("/health")
@app.get("/api/v1/health")
async def health_check():
    """健康检查端点——同时验证数据库连通性，供 CI 部署后探活使用。"""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        logger.error("Health check: DB unreachable: %s", e)
        db_status = "error"

    status = "ok" if db_status == "ok" else "degraded"
    return {"status": status, "db": db_status, "version": "1.0.0"}
