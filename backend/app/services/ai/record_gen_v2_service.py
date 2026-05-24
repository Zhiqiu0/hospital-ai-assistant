"""
病历 JSON 生成 service（services/ai/record_gen_v2_service.py）

L3 治本路线核心 service——把 quick-generate 主路径从"自由文本流"切到
"结构化 JSON → 模板渲染 → 一次性 SSE 推回"。

为什么独立成文件而不在 record_gen_service.py：
  record_gen_service.py 服务于 /api/v1/medical-records/{id}/generate（持久化版本快照），
  本模块服务于 /api/v1/ai/quick-generate（无持久化、纯流式生成草稿）。
  两条路径职责不同，分开文件方便阶段 4 清理旧路径时不互相干扰。

入口：stream_record_v2(record_type, req, db) → AsyncGenerator[str, None]
返回 SSE 字符串生成器，路由层直接 yield 给 StreamingResponse。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_encounter_id, get_user_id
from app.services.ai.ai_utils import sse_event
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.record_prompts import (
    build_polish_prompt,
    build_record_prompt,
)
from app.services.ai.record_renderer import render_record
from app.services.ai.task_logger import log_ai_task

logger = logging.getLogger(__name__)


async def _call_llm_json_with_retry(
    prompt: str,
    opts: dict,
    *,
    max_retries: int = 1,
) -> dict:
    """调 chat_json_stream 拿 JSON dict，失败自动重试 N 次。

    JSON 解析失败 / 网络抖动 / 5xx 都视作可重试错误；
    超出重试上限或非 dict 返回值时抛 ValueError，由上层 SSE 兜底。

    为什么只重试 1 次：DeepSeek-V3.2 实测 JSON 模式失败率 <1%，
    重试 1 次能把端到端失败率压到 0.01% 以下；再多重试只是徒增延迟。
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            result = await llm_client.chat_json_stream(
                [{"role": "user", "content": prompt}],
                temperature=opts["temperature"],
                max_tokens=opts["max_tokens"],
                model_name=opts["model_name"],
            )
            if not isinstance(result, dict):
                raise ValueError(f"LLM 返回非 dict 类型：{type(result).__name__}")
            return result
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "llm_json_retry: attempt=%d/%d err=%s",
                attempt + 1, max_retries + 1, exc,
            )
            # 最后一次直接抛，由上层 SSE error 事件兜底
            if attempt == max_retries:
                raise
    # 不会到这里，typing 兜底
    raise last_exc if last_exc else RuntimeError("unreachable")


def _meta_from_req(req: Any) -> dict:
    """从 req 抽取 renderer 所需元数据（visit_time / onset_time / patient_gender）"""
    return {
        "visit_time": getattr(req, "visit_time", None),
        "onset_time": getattr(req, "onset_time", None),
        "patient_gender": getattr(req, "patient_gender", None),
    }


async def _log_and_save_draft(
    task_type: str,
    record_type: str,
    record_text: str,
    db: AsyncSession,
    *,
    save_draft: bool,
) -> None:
    """写 ai_tasks 审计 + 可选自动落 draft 病历。

    save_draft=True 时仅 generate 路径调用（覆盖式更新草稿）。supplement / polish
    也是更新草稿的——只要 encounter 存在就更新，让医生退出再进来能看到最新草稿。
    """
    usage = llm_client._last_usage
    try:
        await log_ai_task(
            task_type,
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
        )
    except Exception as exc:
        logger.error("log_ai_task_failed task=%s err=%s", task_type, exc)

    if not save_draft:
        return
    encounter_id = get_encounter_id()
    user_id = get_user_id()
    if encounter_id and user_id and user_id != "-":
        try:
            from app.services.medical_record_service import MedicalRecordService
            await MedicalRecordService(db).save_ai_draft(
                encounter_id=encounter_id,
                record_type=record_type,
                content=record_text,
                user_id=user_id,
            )
        except Exception as exc:
            # 草稿保存失败不阻断主流程——前端仍能拿到 chunk
            logger.error("save_ai_draft_failed encounter=%s err=%s", encounter_id, exc)


async def _stream_json_pipeline(
    record_type: str,
    req: Any,
    db: AsyncSession,
    *,
    prompt_builder,  # build_record_prompt / build_supplement_prompt / build_polish_prompt
    task_type: str,  # "generate" / "supplement" / "polish"
    save_draft: bool,
    log_prefix: str,
) -> AsyncGenerator[str, None]:
    """generate / supplement / polish 三家共用的 JSON 主流程。

    步骤：
      1. prompt_builder 构造 LLM 输入
      2. chat_json_stream + retry 拿 dict
      3. render_record 拼装成完整文本（行格式 100% 符合 QC 契约）
      4. 写审计 + 可选保存草稿
      5. SSE 分片推回前端（打字机视觉）

    任何异常都转成 sse_event("error", ...) 推回，避免 StreamingResponse 挂死。
    """
    # 1. 构造 prompt
    try:
        prompt = prompt_builder(record_type, req)
    except Exception as exc:
        logger.exception("%s: prompt_build_failed record_type=%s err=%s",
                         log_prefix, record_type, exc)
        yield sse_event("error", message=f"AI 模板构造失败：{type(exc).__name__}")
        return

    # 2. LLM 调用（带重试）
    try:
        opts = await get_model_options(db, "generate")
        result = await _call_llm_json_with_retry(prompt, opts)
    except Exception as exc:
        logger.exception("%s: llm_failed record_type=%s err=%s", log_prefix, record_type, exc)
        yield sse_event("error", message=f"AI 调用失败：{type(exc).__name__}")
        return

    # 3+5. 渲染 + 分片 SSE（需要先拿到 record_text 用于审计；这里复制 render 逻辑而非调 helper）
    meta = _meta_from_req(req)
    try:
        record_text = render_record(record_type, result, **meta)
    except Exception as exc:
        logger.exception(
            "%s: render_failed record_type=%s err=%s result_keys=%s",
            log_prefix, record_type, exc,
            list(result.keys()) if isinstance(result, dict) else type(result),
        )
        yield sse_event("error", message=f"病历渲染失败：{type(exc).__name__}")
        return

    # 业务里程碑日志（不含病历正文，避免 PHI 入日志）
    logger.info(
        "%s: done record_type=%s fields=%d chars=%d",
        log_prefix, record_type,
        len(result) if isinstance(result, dict) else 0, len(record_text),
    )

    # 4. 审计 + 可选保存草稿
    await _log_and_save_draft(task_type, record_type, record_text, db, save_draft=save_draft)

    # 5. SSE 分片推回（16 字符 / 片 + 20ms sleep）
    chunk_size = 16
    delay = 0.02
    for i in range(0, len(record_text), chunk_size):
        yield sse_event("chunk", text=record_text[i : i + chunk_size])
        await asyncio.sleep(delay)
    yield sse_event("done")


# ─── 三个对外入口（路由层调用） ────────────────────────────────────


async def stream_record_v2(
    record_type: str,
    req: Any,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """quick-generate：JSON 模式生成新病历，自动落草稿。"""
    async for chunk in _stream_json_pipeline(
        record_type, req, db,
        prompt_builder=build_record_prompt,
        task_type="generate",
        save_draft=True,
        log_prefix="record_gen_v2",
    ):
        yield chunk


async def stream_polish_v2(
    record_type: str,
    req: Any,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """quick-polish：JSON 模式润色现有草稿，输出完整 JSON 后渲染。

    与 supplement 区别：prompt 禁止改动客观数据 + 不接受 qc_issues。
    """
    async for chunk in _stream_json_pipeline(
        record_type, req, db,
        prompt_builder=build_polish_prompt,
        task_type="polish",
        save_draft=True,
        log_prefix="record_polish_v2",
    ):
        yield chunk
