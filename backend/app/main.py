from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1 import router as api_v1_router
from app.schema_compat import apply_schema_compatibility

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
    await apply_schema_compatibility()


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}
