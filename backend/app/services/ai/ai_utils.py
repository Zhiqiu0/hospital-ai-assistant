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

logger = logging.getLogger(__name__)


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
    """从数据库读取指定场景的激活 prompt 模板内容。

    Args:
        db: 异步数据库会话。
        scene: prompt 场景标识（如 'generate'、'qc'、'polish'）。

    Returns:
        激活模板的内容字符串，不存在时返回 None（调用方使用内置默认值）。
    """
    result = await db.execute(
        select(PromptTemplate)
        .where(PromptTemplate.scene == scene, PromptTemplate.is_active.is_(True))
        .order_by(PromptTemplate.created_at.desc())
        .limit(1)
    )
    tpl = result.scalar_one_or_none()
    return tpl.content if tpl else None


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
        logger.error("stream_text LLM error: %s", exc, exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    yield 'data: {"type":"done"}\n\n'

    usage = llm_client._last_usage
    await log_ai_task(
        task_type,
        token_input=usage.prompt_tokens if usage else 0,
        token_output=usage.completion_tokens if usage else 0,
    )
