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
from fastapi import APIRouter, Depends, HTTPException, Request

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.rate_limit import ai_limiter
from app.core.security import get_current_user
from app.api.v1.ai_voice import audio_router, router as voice_router
from app.api.v1.ai_generation import router as generation_router
from app.api.v1.ai_suggestions import router as suggestions_router
from app.api.v1.ai_qc import router as qc_router


async def _ai_rate_limit(request: Request) -> None:
    """全局 AI 接口限速依赖（防止滥用 LLM 接口）。"""
    await ai_limiter.check(request)


async def _ai_role_gate(current_user=Depends(get_current_user)) -> None:
    """AI 能力角色门槛（2026-08-29 第七轮渗透审计）。

    此前 /ai/* 全家桶只要登录：限速与单用户锁能封顶不能归零，被前端锁死
    在登录页的 nurse、只读的 qc_officer 持 token 直调 API 仍可消耗 LLM/ASR
    付费额度。AI 生成/质控/建议是医生的病历工作面，按 RECORD_WRITE_ROLES
    同口径收紧（radiologist 的影像 AI 走 /pacs 自有端点，不受影响）。
    """
    from app.core.authz import RECORD_WRITE_ROLES
    if getattr(current_user, "role", None) not in RECORD_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="当前角色无 AI 助手使用权限")


_ai_deps = [Depends(_ai_rate_limit), Depends(_ai_role_gate)]

router = APIRouter()
router.include_router(voice_router, dependencies=_ai_deps)
# 音频回放：只限速不挂角色门槛（query-token 自带鉴权，Bearer 依赖会把
# <audio> 标签的请求全打成 401——2026-08-29 第八轮回归修复）
router.include_router(audio_router, dependencies=[Depends(_ai_rate_limit)])
router.include_router(generation_router, dependencies=_ai_deps)
router.include_router(suggestions_router, dependencies=_ai_deps)
router.include_router(qc_router, dependencies=_ai_deps)
