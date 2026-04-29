"""
AI 路由层共享工具函数（app/services/ai/ai_utils.py）

包含：
  - safe_format          : 安全格式化 prompt 模板
  - get_active_prompt    : 读取 DB 中激活的 prompt 模板
  - stream_text          : LLM 文本 → SSE 流生成器
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import json
import logging
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.models.config import PromptTemplate
from app.services.ai.llm_client import llm_client
from app.services.ai.task_logger import log_ai_task
from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)

# Prompt 模板缓存 key 前缀，按 scene 维度。admin 写模板后调
# invalidate_active_prompt 失效。
_PROMPT_CACHE_KEY = "ai:prompt:{scene}"
_PROMPT_CACHE_TTL = 60


def sse_event(event_type: str, **fields) -> str:
    """SSE 事件序列化：'data: {"type":"...","..."}\\n\\n'。

    项目里多处需要把 LLM 流 / 业务事件包成 SSE 格式推回前端
    （quick-generate / quick-qc / record_gen_v2 / inquiry / record_gen_service 等），
    本 helper 是单一入口，避免每处独立拼字符串导致格式偏差（漏 \\n\\n、
    漏 ensure_ascii=False、type key 拼错等）。

    Args:
        event_type: 事件类型，如 'chunk' / 'done' / 'error' / 'rule_issues'
        **fields:   事件附加字段，与 event_type 一起 json.dumps

    Returns:
        SSE 协议字符串，调用方直接 yield 给 StreamingResponse。
    """
    payload = {"type": event_type, **fields}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def compose_physical_exam(
    physical_exam: Optional[str] = "",
    temperature: Optional[str] = "",
    pulse: Optional[str] = "",
    respiration: Optional[str] = "",
    bp_systolic: Optional[str] = "",
    bp_diastolic: Optional[str] = "",
    spo2: Optional[str] = "",
    height: Optional[str] = "",
    weight: Optional[str] = "",
) -> str:
    """将独立的生命体征字段与 physical_exam 文字描述合并，供 AI 生成病历时作为完整体检段使用。

    前端 UI 把生命体征数值和文字描述分成两部分输入（前者结构化，后者自由文本），
    但 AI 生成病历时需要看到完整的体检段落。本函数生成标准格式的前缀：
        T:36.5℃  P:72次/分  R:18次/分  BP:120/80mmHg  SpO₂:98%  身高:170cm  体重:65kg\n
    后面拼接用户原本的 physical_exam 文字描述（心肺听诊/腹部触诊等）。

    所有字段均为空时返回空串（让 prompt 侧显示"未提供"）。
    """
    parts: list[str] = []
    if temperature:
        parts.append(f"T:{temperature}℃")
    if pulse:
        parts.append(f"P:{pulse}次/分")
    if respiration:
        parts.append(f"R:{respiration}次/分")
    if bp_systolic or bp_diastolic:
        parts.append(f"BP:{bp_systolic or '__'}/{bp_diastolic or '__'}mmHg")
    if spo2:
        parts.append(f"SpO₂:{spo2}%")
    if height:
        parts.append(f"身高:{height}cm")
    if weight:
        parts.append(f"体重:{weight}kg")

    vital_prefix = "  ".join(parts)
    text = (physical_exam or "").strip()
    if vital_prefix and text:
        return f"{vital_prefix}\n{text}"
    return vital_prefix or text


def safe_format(template: str, **kwargs) -> str:
    """安全格式化 prompt 模板，转义值中的花括号以防 KeyError。

    Args:
        template: 含 {placeholder} 的 prompt 字符串。
        **kwargs: 填充占位符的键值对。

    Returns:
        格式化后的字符串。
    """
    safe_kwargs = {k: str(v).replace("{", "{{").replace("}", "}}") for k, v in kwargs.items()}
    return template.format(**safe_kwargs)


async def get_active_prompt(db: AsyncSession, scene: str) -> Optional[str]:
    """从数据库读取指定场景的激活 prompt 模板内容（带 Redis 缓存）。

    Args:
        db: 异步数据库会话。
        scene: prompt 场景标识（如 'generate'、'qc'、'polish'）。

    Returns:
        激活模板的内容字符串，不存在时返回 None（调用方使用内置默认值）。

    缓存：
      Redis 60 秒 TTL；admin 修改 PromptTemplate 后调用
      invalidate_active_prompt(scene) 主动失效。
      "无模板"（None）也缓存为 {"none": True} 避免穿透打 DB。
    """
    cache_key = _PROMPT_CACHE_KEY.format(scene=scene)
    cached = await redis_cache.get_json(cache_key)
    if cached is not None:
        # 用占位对象表示"明确无模板"，区分缓存未命中与"DB 中确实没有"
        return None if cached.get("none") else cached.get("content")

    result = await db.execute(
        select(PromptTemplate)
        .where(PromptTemplate.scene == scene, PromptTemplate.is_active.is_(True))
        .order_by(PromptTemplate.created_at.desc())
        .limit(1)
    )
    tpl = result.scalar_one_or_none()
    content = tpl.content if tpl else None
    await redis_cache.set_json(
        cache_key,
        {"content": content} if content else {"none": True},
        ttl=_PROMPT_CACHE_TTL,
    )
    return content


async def invalidate_active_prompt(scene: str | None = None) -> None:
    """admin 修改 PromptTemplate 后调用，立即让所有进程看到新模板。"""
    if scene:
        await redis_cache.delete(_PROMPT_CACHE_KEY.format(scene=scene))
    else:
        await redis_cache.delete_prefix("ai:prompt:")


async def stream_with_lock(generator, lock_key: str, lock_token: str):
    """包装 SSE 生成器，在流结束/异常时释放锁。

    用法：
        token = await redis_cache.acquire_lock(key, ttl=120)
        if not token: raise HTTPException(429, "...")
        return StreamingResponse(
            stream_with_lock(stream_text(...), key, token),
            media_type="text/event-stream",
        )

    LLM 流式接口可能跑 30-60s，期间用户重复点击会发起新流；用锁包住整个流，
    第二次请求看到锁存在直接 409，避免烧 token + 写库冲突。
    """
    try:
        async for chunk in generator:
            yield chunk
    finally:
        await redis_cache.release_lock(lock_key, lock_token)


async def stream_text(
    prompt: str,
    task_type: str = "generate",
    model_options: Optional[dict] = None,
):
    """将 LLM 文本响应包装为 SSE 流，完成后异步记录 token 用量。

    Args:
        prompt: 发送给 LLM 的完整 prompt 字符串。
        task_type: 用于审计日志的任务类型标识（如 'generate'、'polish'）。
        model_options: 包含 model_name/temperature/max_tokens 的配置字典。

    Yields:
        SSE 格式字符串，事件类型：start / chunk / error / done。
    """
    yield 'data: {"type":"start"}\n\n'
    messages = [{"role": "user", "content": prompt}]
    options = model_options or {}
    try:
        async for chunk in llm_client.stream(
            messages,
            temperature=options.get("temperature", 0.3),
            max_tokens=options.get("max_tokens", 4096),
            model_name=options.get("model_name"),
        ):
            payload = json.dumps({"type": "chunk", "text": chunk}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
    except Exception as exc:
        logger.exception("ai.stream_text: failed err=%s", exc)
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    yield 'data: {"type":"done"}\n\n'

    usage = llm_client._last_usage
    await log_ai_task(
        task_type,
        token_input=usage.prompt_tokens if usage else 0,
        token_output=usage.completion_tokens if usage else 0,
    )
