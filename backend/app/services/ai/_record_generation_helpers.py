"""病历模型调用与真实性守卫；独立于 SSE 编排。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.ai.ai_utils import guarded_messages
from app.services.ai.llm_client import LLMServiceError, llm_client
from app.services.ai.output_contracts import validate_record_output
from app.services.ai.output_guards import strip_unsubstantiated_vitals

logger = logging.getLogger(__name__)


class DraftSaveError(RuntimeError):
    """文本已生成但保存失败，由 SSE 完成事件披露并保留前端自动保存恢复。"""

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



async def _call_llm_json_with_retry(
    prompt: str,
    opts: dict,
    *,
    record_type: str = "outpatient",
    max_retries: int = 1,
) -> dict:
    """调 chat_json_stream 拿 JSON dict，失败自动重试 N 次。

    JSON 解析失败 / 网络抖动 / 5xx 都视作可重试错误；
    超出重试上限或非 dict 返回值时抛 ValueError，由上层 SSE 兜底。

    默认只重试一次，在恢复瞬时失败与限制响应延迟之间取平衡；
    重试不保证成功，持续结构错误仍交由上层明确报错并保留原稿。
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
            # 在有限重试内部检查模板契约，禁止错误对象被渲染成占位草稿。
            return validate_record_output(result, record_type)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "llm_json_retry: attempt=%d/%d status=%s err=%s",
                attempt + 1, max_retries + 1,
                getattr(exc, "status_code", "-"), exc,
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
