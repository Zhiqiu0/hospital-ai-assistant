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
from app.services.ai.record_prompts import build_record_prompt
from app.services.ai.record_renderer import render_record
from app.services.ai.task_logger import log_ai_task

logger = logging.getLogger(__name__)


async def stream_record_v2(
    record_type: str,
    req: Any,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """JSON 模式生成 → 渲染 → SSE 一次性推回。

    流程：
      1. build_record_prompt 构造 LLM 输入（schema 字段说明 + 医生录入数据）
      2. chat_json_stream 拿 dict（流式累积 token，避免大 max_tokens 超时）
      3. render_record 按模板拼成完整文本（行格式 100% 符合 QC 契约）
      4. 把完整文本切片 + 节流 SSE 推回前端（打字机视觉）

    与旧 stream_text 的差异：
      - 旧：LLM 边写边推 free text（打字机 + 格式不可控）
      - 新：LLM 完整 JSON → render 成 100% QC 合规文本 → 服务端分片 + sleep 节流推回
        前端依旧 onChunk 增量 append，视觉表现仍是打字机
      - 治本 bug（行格式必正确）+ 保留打字机体验，代价是 LLM 生成完之后还要多 1~2s 节流时间

    异常处理：
      - LLM 调用失败 → 推 error 事件，前端 toast
      - JSON 字段缺失 → render_record 内部用 PLACEHOLDER 兜底，不会崩
    """
    try:
        prompt = build_record_prompt(record_type, req)
    except Exception as exc:
        # 包括 ValueError（白名单外 record_type）、NameError / AttributeError
        # （prompt 构造代码本身的 bug）、TypeError（req 字段缺失）等。
        # 必须 catch 全部——任何异常漏出 SSE 生成器，会让前端连接挂着干等
        # （StreamingResponse 不会主动关），用户感知就是"卡住了"。
        logger.exception("record_gen_v2: prompt_build_failed record_type=%s err=%s",
                         record_type, exc)
        yield sse_event("error", message=f"病历模板构造失败：{type(exc).__name__}")
        return

    try:
        opts = await get_model_options(db, "generate")
        result = await llm_client.chat_json_stream(
            [{"role": "user", "content": prompt}],
            temperature=opts["temperature"],
            max_tokens=opts["max_tokens"],
            model_name=opts["model_name"],
        )
    except Exception as exc:
        logger.exception("record_gen_v2: llm_failed record_type=%s err=%s", record_type, exc)
        yield sse_event("error", message=f"AI 生成失败：{type(exc).__name__}")
        return

    # render_record 入参 meta：visit_time / onset_time / patient_gender 从 req 拿
    # （请求层元数据，住院记录据 patient_gender 决定是否输出【月经史】章节）
    meta = {
        "visit_time": getattr(req, "visit_time", None),
        "onset_time": getattr(req, "onset_time", None),
        "patient_gender": getattr(req, "patient_gender", None),
    }
    try:
        record_text = render_record(record_type, result, **meta)
    except Exception as exc:
        # render 出错说明 LLM 返回的 JSON 结构异常或 record_type 路由 bug，记日志后兜底
        logger.exception(
            "record_gen_v2: render_failed record_type=%s err=%s result_keys=%s",
            record_type, exc, list(result.keys()) if isinstance(result, dict) else type(result),
        )
        yield sse_event("error", message=f"病历渲染失败：{type(exc).__name__}")
        return

    # 业务里程碑：JSON 生成成功（不含病历正文，避免 PHI 入日志）
    logger.info(
        "record_gen_v2: done record_type=%s fields=%d chars=%d",
        record_type, len(result) if isinstance(result, dict) else 0, len(record_text),
    )

    # 写 ai_tasks（合规追溯，自动从 RequestContext 取 encounter_id）
    usage = llm_client._last_usage
    try:
        await log_ai_task(
            "generate",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
        )
    except Exception as exc:
        logger.error("record_gen_v2: log_ai_task_failed err=%s", exc)

    # ★ 治本：自动落 draft 病历到 DB——logout 后再回来能拿到
    # 路由层已通过 bind_encounter_context 注入 encounter_id；user_id 来自鉴权 dependency
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
            # 但要记日志，方便排查"为什么 logout 后丢草稿"
            logger.error("record_gen_v2: save_ai_draft_failed encounter=%s err=%s", encounter_id, exc)

    # 分片节流推回，前端 onChunk 增量 append，视觉表现为打字机
    # 参数取值：16 字符 / 片 + 20ms sleep —— 1500 字病历约 94 片 ≈ 1.9s
    # 太大（>32 字符）跳字感明显；太小 / sleep 太短 SSE 包数过多浪费带宽
    chunk_size = 16
    delay = 0.02
    for i in range(0, len(record_text), chunk_size):
        yield sse_event("chunk", text=record_text[i : i + chunk_size])
        await asyncio.sleep(delay)
    yield sse_event("done")
