"""
病历 JSON 生成 service（services/ai/record_gen_v2_service.py）

L3 治本路线核心 service——把 quick-generate 主路径从"自由文本流"切到
"结构化 JSON → 模板渲染 → 一次性 SSE 推回"。

历史说明：旧范式 record_gen_service.py（/medical-records/{id}/generate 系列）
已于 2026-08-12 清理删除，本模块是病历 AI 生成的唯一路径。

入口：stream_record_v2(record_type, req, db) → AsyncGenerator[str, None]
返回 SSE 字符串生成器，路由层直接 yield 给 StreamingResponse。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_encounter_id, get_user_id
from app.services.ai.ai_utils import guarded_messages, sse_event
from app.services.ai.llm_client import LLMServiceError, llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.record_prompts import (
    build_polish_prompt,
    build_record_prompt,
)
from app.services.ai.output_guards import strip_unsubstantiated_vitals
from app.services.ai.record_renderer import render_record
from app.services.ai.task_logger import log_ai_task

logger = logging.getLogger(__name__)

# 会被数值守卫检查的字段：生命体征行 + 阳性体征描述（AI 可能在这两处编造数值）。
# 诊断/治则等临床判断字段不查——它们允许基于上下文合理推断，无客观数值。
# physical_exam_today 是**住院病程记录/术后记录**的查体字段（见
# record_schemas_inpatient.py），schema 描述直接要求 LLM 输出
# "T:__℃ P:__次/分 R:__次/分 BP:__/__mmHg"——漏掉它等于住院这条最高频的文书
# 路径上守卫完全没装，AI 编的体征直接进病历并自动落草稿（2026-08-14 第六轮审计修复）。
_VITALS_GUARDED_FIELDS = (
    "physical_exam_vitals",
    "physical_exam_text",
    "physical_exam_today",
)


def _guard_vitals_in_result(result: Any, req: Any) -> None:
    """主生成路径数值真实性守卫（2026-08-11 病历安全）：就地剔除 result 里数值无出处
    的生命体征 token。原先该确定性守卫只在质控修复链生效，产量最大的"首次生成"出口
    反而没装——AI 编造 T/P/R/BP 而医生没测就签发是数值真实性最高危敞口。

    source_text 只取医生录入的原始体征/病史字段，AI 生成的其它字段不算出处。
    """
    if not isinstance(result, dict):
        return
    # 医生录入的真实体征数值 + 体检/主诉/现病史文字——凡在这里出现过的数字才算"有出处"
    source_text = "\n".join(
        str(getattr(req, f, "") or "")
        for f in ("temperature", "pulse", "respiration", "bp_systolic", "bp_diastolic",
                  "spo2", "height", "weight", "physical_exam",
                  "chief_complaint", "history_present_illness",
                  # 医生在正文里手改的数值也算出处（2026-08-14 第六轮审计修复）：
                  # 正文是本产品的主编辑入口，医生把血压改成实测值后不会回左侧
                  # 问诊面板同步。原先出处不含它 → 润色时守卫认为该数值"查无出处"，
                  # 把整个 BP token 剔除，医生只看到半行没了、毫无提示，
                  # 而润色 prompt 明写"严禁修改任何客观数值"——LLM 老实照抄了，
                  # 却被后端守卫删掉，自相矛盾。
                  # run_qc_fix 早就把 current_record 计入出处，说明"正文算出处"
                  # 本就是本项目的既定口径，只有生成/润色这条路径漏了。
                  "current_content", "current_record")
    )
    for field in _VITALS_GUARDED_FIELDS:
        val = result.get(field)
        if isinstance(val, str) and val:
            cleaned = strip_unsubstantiated_vitals(val, source_text)
            if cleaned != val:
                logger.warning("record_gen.guard: stripped_fabricated_vitals field=%s", field)
                result[field] = cleaned


# SSE 静默期心跳间隔（秒）：远小于 nginx 300s proxy_read_timeout 即可
_HEARTBEAT_INTERVAL = 15.0


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
                guarded_messages(prompt),
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
            # 确定性失败（欠费/凭证无效/输出截断）重试注定同样失败，
            # 立即上抛省掉一次白烧的计费（2026-08-28 全量体检）
            if isinstance(exc, LLMServiceError) and not exc.retryable:
                raise
            # 最后一次直接抛，由上层 SSE error 事件兜底
            if attempt == max_retries:
                raise
            # 重试前短退避（2026-06-11）：给上游瞬时抖动（限流/5xx/网络）恢复时间，
            # 立刻重试大概率撞上同一个故障窗口
            await asyncio.sleep(1.0 * (attempt + 1))
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
    model_name: str | None = None,
) -> str | None:
    """写 ai_tasks 审计 + 可选自动落 draft 病历。

    save_draft=True 时仅 generate 路径调用（覆盖式更新草稿）。supplement / polish
    也是更新草稿的——只要 encounter 存在就更新，让医生退出再进来能看到最新草稿。

    Returns:
        草稿落库后的 updated_at ISO 字符串（未落库/失败时 None）——done 事件带给
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
            # 草稿保存失败不阻断主流程——前端仍能拿到 chunk
            logger.error("save_ai_draft_failed encounter=%s err=%s", encounter_id, exc)
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
        llm_task = asyncio.ensure_future(_call_llm_json_with_retry(prompt, opts))
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
        msg = exc.user_message if isinstance(exc, LLMServiceError) \
            else f"AI 调用失败：{type(exc).__name__}"
        yield sse_event("error", message=msg)
        return

    # 2.5 数值真实性守卫：剔除 AI 编造、医生录入里查无出处的生命体征数值（病历安全红线）
    _guard_vitals_in_result(result, req)

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
    saved_updated_at = await _log_and_save_draft(
        task_type, record_type, record_text, db,
        save_draft=save_draft, model_name=opts.get("model_name"),
    )

    # 5. SSE 分片推回（16 字符 / 片 + 20ms sleep）
    chunk_size = 16
    delay = 0.02
    for i in range(0, len(record_text), chunk_size):
        yield sse_event("chunk", text=record_text[i : i + chunk_size])
        await asyncio.sleep(delay)
    # done 事件携带草稿落库时间，前端据此同步 auto-save 乐观锁基线（防生成后假 409）
    if saved_updated_at:
        yield sse_event("done", saved_updated_at=saved_updated_at)
    else:
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
