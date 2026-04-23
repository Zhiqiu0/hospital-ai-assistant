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
