"""
AI 病历生成路由（/api/v1/ai/quick-generate 等）

端点列表：
  POST   /quick-generate      流式生成指定类型病历草稿
  POST   /quick-supplement    根据质控问题一键补全病历（流式）
  POST   /quick-polish        病历润色（流式）
  POST   /normalize-fields    问诊字段规范化（口语→书面）
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import get_current_user
from app.database import get_db
from app.services.audit_service import log_action
from app.schemas.ai_request import (
    NormalizeFieldsRequest,
    PolishRequest,
    QuickGenerateRequest,
    SupplementRequest,
)
from app.services.ai.ai_utils import (
    compose_physical_exam,
    stream_with_lock,
)
from app.services.ai.field_normalize_service import run_normalize_fields
from app.services.ai.model_options import get_model_options
from app.services.ai.prompts import RECORD_TYPE_LABELS
from app.services.ai.record_gen_v2_service import (
    stream_polish_v2,
    stream_record_v2,
)
from app.services.ai.supplement_batch_service import run_quick_supplement_batch
from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)


async def _acquire_ai_gen_lock(user_id: str, scope: str) -> tuple[str, str]:
    """为 AI 流式生成接口拿锁，已被占用则直接 409。

    锁 key 含 user_id + scope，让同一医生同时只能跑一个生成任务（极少有合理用例
    要并行跑两份病历草稿）。

    ttl=300s 对齐 nginx SSE 超时（2026-08-28 体检修正）：原 120s 只覆盖"正常"
    耗时，LLM 慢/重试中锁先过期，医生再点一次就两股生成流并发双份计费——
    恰是抖动/欠费日最需要防重复点击的时候。300s 后 nginx 也会掐流，锁活得
    比流长即可；流正常结束时锁会被主动释放，不会让医生干等 5 分钟。
    """
    lock_key = f"lock:ai_gen:{user_id}:{scope}"
    token = await redis_cache.acquire_lock(lock_key, ttl=300)
    if token is None:
        raise HTTPException(
            status_code=429,
            detail="您有一个 AI 生成任务正在进行中，请等待完成后再试",
        )
    return lock_key, token


router = APIRouter()


@router.post("/quick-generate")
async def quick_generate(
    req: QuickGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """根据问诊信息流式生成指定类型的病历草稿。"""
    # 把接诊维度写入 RequestContext，下游 log_ai_task 自动取用——
    # 让 ai_tasks.encounter_id 能正确绑定（合规追溯 + snapshot 恢复需要）
    from app.core.request_context import bind_encounter_context
    bind_encounter_context(
        encounter_id=req.encounter_id,
        medical_record_id=req.medical_record_id,
    )

    # 审计：记录医生对哪个病历类型调了 AI 生成（医疗场景合规要求）
    await log_action(
        action="ai_quick_generate",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        detail=f"record_type={req.record_type or 'outpatient'}",
    )
    # 急诊接诊自动选急诊 record_type，除非医生已明确指定其他类型
    is_emergency = (req.visit_type_detail or "outpatient") == "emergency"
    record_type = req.record_type or ("emergency" if is_emergency else "outpatient")

    # L3 新架构：所有病历生成统一走"JSON 模式 → renderer 拼文本 → SSE 推回"
    # 行格式由后端模板严格控制，永远符合 QC 契约。
    # 白名单外的 record_type 由 service 内部抛 error 事件让前端 toast。
    lock_key, lock_token = await _acquire_ai_gen_lock(current_user.id, "generate")
    return StreamingResponse(
        stream_with_lock(
            stream_record_v2(record_type, req, db),
            lock_key, lock_token,
        ),
        media_type="text/event-stream",
    )


@router.post("/quick-supplement")
async def quick_supplement(
    req: SupplementRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """批量补全（行级写入路线）：一次 LLM 调用返回所有缺失字段的建议值。

    治本路线（2026-05-24）—— 替换旧"整段重画"实现：
      旧：LLM 重写完整 JSON → renderer 整段重画 → 覆盖医生现场修改
           （bug：78 分逐条补全后整体补全回到 70）
      新：LLM 一次返回 N 个 {field_name, value}，前端按 FIELD_TO_LINE_PREFIX
           行级写入 —— 与"逐条修复"同一套机制，杜绝整段覆盖。

    返回格式（非 SSE，普通 JSON 响应）：
      {"items": [{"field_name": "舌象", "value": "..."}, ...]}
    """
    await log_action(
        action="ai_quick_supplement",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        detail=f"record_type={req.record_type or 'outpatient'} issues_count={len(req.qc_issues or [])}",
    )
    # 没有 qc_issues 时直接返回空（前端往往是误触；不浪费 LLM 调用）
    if not req.qc_issues:
        return {"items": []}

    # 仍然走 AI 生成锁，避免同一医生并发跑多次补全
    lock_key, lock_token = await _acquire_ai_gen_lock(current_user.id, "supplement")
    try:
        return await run_quick_supplement_batch(db, req)
    finally:
        # 锁是 redis_cache 实现，token 不匹配则跳过删除（防误删别人的锁）
        try:
            await redis_cache.release_lock(lock_key, lock_token)
        except Exception:
            pass


@router.post("/quick-polish")
async def quick_polish(
    req: PolishRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """润色病历（JSON 模式 + renderer 重渲染）。

    与 supplement 同构，但 prompt 禁止改动客观数据；输出经 renderer 拼装，
    永远符合 QC 行格式契约。
    """
    await log_action(
        action="ai_quick_polish",
        user_id=current_user.id,
        user_name=current_user.username,
        user_role=current_user.role,
        resource_type="medical_record",
        detail=f"record_type={req.record_type or 'outpatient'}",
    )
    # 空草稿没有润色对象，直接 done
    if not (req.current_content or "").strip():
        return StreamingResponse(
            iter(['data: {"type":"done"}\n\n']),
            media_type="text/event-stream",
        )

    record_type = req.record_type or "outpatient"
    lock_key, lock_token = await _acquire_ai_gen_lock(current_user.id, "polish")
    return StreamingResponse(
        stream_with_lock(
            stream_polish_v2(record_type, req, db),
            lock_key, lock_token,
        ),
        media_type="text/event-stream",
    )


@router.post("/normalize-fields")
async def normalize_fields(
    req: NormalizeFieldsRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """将修改的问诊字段规范化（口语→书面，去重，格式统一），返回整理后的字段值。"""
    if not req.fields:
        return {"fields": {}}
    # prompt 组装 + LLM 调用 + 解析全在 service（失败时原样返回，不阻塞保存）
    return await run_normalize_fields(db, req.fields)
