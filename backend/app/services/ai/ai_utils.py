"""
AI 路由层共享工具函数（app/services/ai/ai_utils.py）

包含：
  - safe_format          : 安全格式化 prompt 模板

历史：get_active_prompt（从 prompt_templates 表读管理员自定义提示词）已删
（2026-08-18）——提示词归代码 prompts_*.py 唯一维护，后台不再可改。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import json
import logging
from typing import Optional

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.services.redis_cache import redis_cache

logger = logging.getLogger(__name__)


def sse_event(event_type: str, **fields) -> str:
    """SSE 事件序列化：'data: {"type":"...","..."}\\n\\n'。

    项目里多处需要把 LLM 流 / 业务事件包成 SSE 格式推回前端
    （quick-generate / quick-qc / record_gen_v2 / inquiry 等），
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
    """格式化 prompt 模板（值统一转字符串）。

    2026-08-12 复检修复：删掉原来对值里花括号的 {{ }} 转义——str.format 只解析
    模板本身、不会二次解析替换进去的值，转义防不了任何 KeyError，反而让医生
    正文里的 {"WBC":9.8} 在发给 LLM 的 prompt 中变成 {{"WBC":9.8}}（文本失真）。

    Args:
        template: 含 {placeholder} 的 prompt 字符串（模板内字面花括号写 {{}}）。
        **kwargs: 填充占位符的键值对。

    2026-08-14 第七轮审计修复：**它此前并不 safe**。
      模板来源当时是 get_active_prompt——即管理员在「提示词管理」页自己写的内容
      （该页与 DB 模板已于 2026-08-18 撤掉，模板现全部来自代码，但保护逻辑保留）。
      只要里面出现一个未提供的占位符（如 {patient_name}）或一个裸的 `{`，
      str.format 就抛 KeyError / ValueError / IndexError，而各调用点这一行都在
      try 之外 → **整个端点恒 500**（追问建议、检查建议、诊断建议、质控、
      批量补全六处调用全中招）。管理员改一个提示词就能让全院医生的 AI 功能瘫痪，
      且报错信息里看不出是提示词的问题。
      现在：格式化失败时**退回原模板**并记 warning——AI 拿到带占位符的原文
      仍能工作（效果打折），远好过整个功能不可用。

    Returns:
        格式化后的字符串；模板本身有问题时返回原模板。
    """
    values = {k: str(v) for k, v in kwargs.items()}
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning(
            "ai.safe_format: 模板格式化失败，退回原模板（多半是自定义提示词里有"
            "未知占位符或未转义的花括号）err=%s 已提供的占位符=%s",
            exc, sorted(values),
        )
        return template


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


