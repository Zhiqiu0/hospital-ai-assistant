"""
AI 路由聚合器（/api/v1/ai/*）

将四个子域路由挂载为统一的 /ai 前缀路由，并在聚合层统一应用限速中间件。
子模块职责划分：
  ai_voice.py       : 语音上传 / 播放 / 删除 / 结构化
  ai_generation.py  : 病历生成 / 续写 / 补全 / 润色 / 字段规范化
  ai_suggestions.py : 追问建议 / 检查建议 / 诊断建议
  ai_qc.py          : 质控扫描 / 问题修复 / 甲级评分
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, Request

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.rate_limit import ai_limiter
from app.api.v1.ai_voice import router as voice_router
from app.api.v1.ai_generation import router as generation_router
from app.api.v1.ai_suggestions import router as suggestions_router
from app.api.v1.ai_qc import router as qc_router


async def _ai_rate_limit(request: Request) -> None:
    """全局 AI 接口限速依赖（防止滥用 LLM 接口）。"""
    await ai_limiter.check(request)


_rate_limit_dep = [Depends(_ai_rate_limit)]

router = APIRouter()
router.include_router(voice_router, dependencies=_rate_limit_dep)
router.include_router(generation_router, dependencies=_rate_limit_dep)
router.include_router(suggestions_router, dependencies=_rate_limit_dep)
router.include_router(qc_router, dependencies=_rate_limit_dep)
