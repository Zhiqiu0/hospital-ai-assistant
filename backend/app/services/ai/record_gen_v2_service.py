"""病历生成与润色：完整 JSON 契约校验 → 模板渲染 → 保存草稿 → SSE。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_encounter_id, get_user_id
from app.services.ai.ai_utils import sse_event
from app.services.ai.llm_client import LLMServiceError, llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.output_contracts import AIOutputContractError, validate_record_output
from app.services.ai.record_prompts import (
    build_polish_prompt,
    build_record_prompt,
)
from app.services.ai.output_guards import (
    strip_unsourced_copy_fields,
)
from app.services.ai.record_renderer import render_record
from app.services.ai.task_logger import log_ai_task
# 保留既有导入路径，供调用方和真实性守卫回归测试复用拆分后的辅助函数。
from app.services.ai._record_generation_helpers import (  # noqa: F401
    DraftSaveError, _VITALS_GUARDED_FIELDS, _guard_vitals_in_result, _call_llm_json_with_retry,
)

logger = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 15.0


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
    model_name: str | None = None,
) -> str | None:
    """写 ai_tasks 审计 + 可选自动落 draft 病历。

    save_draft=True 时仅 generate 路径调用（覆盖式更新草稿）。supplement / polish
    也是更新草稿的——只要 encounter 存在就更新，让医生退出再进来能看到最新草稿。

    Returns:
        草稿落库后的 updated_at ISO 字符串（未落库时 None；失败抛 DraftSaveError）——done 事件带给
        前端同步 auto-save 乐观锁基线（2026-08-21 第四轮走查：生成落库后前端
        基线不知道这次写入，下一次 auto-save 必假 409）。
    """
    usage = llm_client._last_usage
    try:
        await log_ai_task(
            task_type,
            token_input=usage.prompt_tokens if usage else None,
            token_output=usage.completion_tokens if usage else None,
            model_name=model_name,  # 真实模型，非全局默认（审计 #7）
        )
    except Exception as exc:
        logger.error("log_ai_task_failed task=%s err=%s", task_type, exc)

    if not save_draft:
        return None
    encounter_id = get_encounter_id()
    user_id = get_user_id()
    if encounter_id and user_id and user_id != "-":
        try:
            from app.services.medical_record_service import MedicalRecordService
            saved = await MedicalRecordService(db).save_ai_draft(
                encounter_id=encounter_id,
                record_type=record_type,
                content=record_text,
                user_id=user_id,
            )
            return saved.get("updated_at")
        except Exception as exc:
            # 单独披露保存失败，后续仍发送生成文本供医生保留及自动保存恢复。
            logger.error("save_ai_draft_failed encounter=%s err=%s", encounter_id, exc)
            raise DraftSaveError("病历已生成，但草稿保存失败，请检查保存状态并重试") from exc
    return None


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
        opts = get_model_options("generate")
        # 连接池护栏：进入最长 270s 的 LLM 调用前先 commit 结束本请求此前的只读事务（若有）、
        # 只读事务、把 asyncpg 连接还回池——否则 quick-generate/polish/supplement 的
        # 整个流式期间都白占一条池连接，多医生并发就把 30 连接的池占满。
        # 后续 _log_and_save_draft 的写走独立/重新借的连接，不受影响。
        await db.commit()
        # 静默期心跳（2026-08-28 体检收尾）：JSON 管线在 LLM 完整返回前对客户端
        # 零字节输出，LLM 慢/重试时静默可超 nginx 的 300s proxy_read_timeout，
        # nginx 会掐流让医生看到莫名失败而后端还在跑。把 LLM 调用挪进后台任务，
        # 每 15s 吐一行 SSE 注释（": ping"）保活——前端解析器只认 data: 行，
        # 注释行天然被忽略，行为零变化。
        llm_task = asyncio.ensure_future(_call_llm_json_with_retry(
            prompt, opts, record_type=record_type))
        try:
            while True:
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(llm_task), timeout=_HEARTBEAT_INTERVAL)
                    break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except BaseException:
            # 客户端断开（GeneratorExit）或其他异常时取消 LLM 任务，不留孤儿
            if not llm_task.done():
                llm_task.cancel()
            raise
    except Exception as exc:
        logger.exception("%s: llm_failed record_type=%s err=%s", log_prefix, record_type, exc)
        # 业务化异常带医生可读文案（欠费→"请联系管理员充值"），其余保留类型名
        msg = exc.user_message if isinstance(exc, (LLMServiceError, AIOutputContractError)) \
            else f"AI 调用失败：{type(exc).__name__}"
        yield sse_event("error", message=msg)
        return

    # 2.5 数值真实性守卫：剔除 AI 编造、医生录入里查无出处的生命体征数值（病历安全红线）
    _guard_vitals_in_result(result, req)
    # 照抄类字段守卫（2026-09-02 AI 输出安全面）：诊断 / 治则治法 / 处理意见 /
    # 注意事项在 prompt 里要求"严格照抄，不改写"，医生没录入就不该凭空出现。
    # 拦两类东西：被 prompt 注入诱导写出的假诊断与危险医嘱（实测三条全中，
    # 且 prompt 侧的定界与声明挡不住），以及模型自行"补全"出的一套诊疗方案
    # ——后者更常见，看起来完全合理，最容易被医生直接签发。
    reverted = strip_unsourced_copy_fields(result, req)
    if reverted:
        logger.warning(
            "record_gen.guard: 医生未录入却被 AI 填出内容，已回退为占位符 fields=%s",
            ",".join(reverted),
        )

    # 守卫可能剔除唯一有内容的字段；保存前重验，避免整份占位稿覆盖医生原稿。
    try:
        validate_record_output(result, record_type)
    except AIOutputContractError as exc:
        yield sse_event("error", message=exc.user_message)
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
    save_warning = None
    try:
        saved_updated_at = await _log_and_save_draft(
            task_type, record_type, record_text, db,
            save_draft=save_draft, model_name=opts.get("model_name"))
    except DraftSaveError as exc:
        saved_updated_at, save_warning = None, str(exc)

    # 5. SSE 分片推回（16 字符 / 片 + 20ms sleep）
    chunk_size = 16
    delay = 0.02
    for i in range(0, len(record_text), chunk_size):
        yield sse_event("chunk", text=record_text[i : i + chunk_size])
        await asyncio.sleep(delay)
    # done 事件携带草稿落库时间，前端据此同步 auto-save 乐观锁基线（防生成后假 409）
    if save_warning:
        yield sse_event("done", saved=False, warning=save_warning)
    elif saved_updated_at:
        yield sse_event("done", saved_updated_at=saved_updated_at)
    else:
        yield sse_event("done")


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
