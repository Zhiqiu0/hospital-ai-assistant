"""病历批量补全 service（services/ai/supplement_batch_service.py）

治本路线（2026-05-24）——替换 record_gen_v2_service.stream_supplement_v2：
  旧：LLM 重写完整病历 JSON → renderer 整段重画 → 覆盖医生现场修改
       （bug：78 分逐条补全后整体补全回到 70）
  新：复用 QC_FIX_BATCH_PROMPT 的"医生书写助手"风格，一次 LLM 调用返回所有
       缺失字段的建议值，前端按 FIELD_TO_LINE_PREFIX 行级写入 ——
       与"逐条修复"同一套机制，杜绝整段覆盖。

入口：run_quick_supplement_batch(db, req) → dict（一次性 JSON 返回，无 SSE）
返回格式：{"items": [{"field_name": "舌象", "value": "..."}, ...]}
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.ai_utils import safe_format
from app.services.ai.llm_client import llm_client
from app.services.ai.model_options import get_model_options
from app.services.ai.output_guards import strip_unsubstantiated_vitals
from app.services.ai.prompts_qc import QC_FIX_BATCH_PROMPT
from app.services.ai.task_logger import log_ai_task


logger = logging.getLogger(__name__)


def _render_issues_block(qc_issues: list) -> tuple[str, int]:
    """把 QC 问题列表渲染成 prompt 里"待修复字段清单"的多行文本。

    每条问题渲染成单行："N. 字段：xxx，问题：xxx，建议：xxx"。
    field_name 为空的条目跳过（无法对应字段的 issue 不能批量补全，例如
    患者基本信息/就诊时间这类不在病历正文里的字段）。

    Returns:
        (issues_block 文本, 有效条目数)
    """
    lines: list[str] = []
    for item in qc_issues:
        if not isinstance(item, dict):
            continue
        field_name = (item.get("field_name") or "").strip()
        if not field_name:
            continue
        # 跳过 __xxx__ 这类 NON_WRITABLE 标记字段（写入会错位，由前端 UI 引导）
        if field_name.startswith("__") and field_name.endswith("__"):
            continue
        desc = (item.get("issue_description") or "").strip()
        advice = (item.get("suggestion") or "").strip()
        idx = len(lines) + 1
        lines.append(f"{idx}. 字段：{field_name}，问题：{desc or '缺失或不规范'}，建议：{advice or '请补充'}")
    return "\n".join(lines), len(lines)


def _validate_items(raw: Any, allowed_fields: set[str]) -> list[dict]:
    """校验 LLM 返回的 items 结构 + 字段名白名单。

    规则：
      - 必须是 list
      - 每项是 dict 且含 field_name + value
      - field_name 必须在 allowed_fields 里（防 LLM 编造新字段名造成前端写入错位）
      - value 是非空字符串
      - 同名字段去重保留首个
    """
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        field_name = (item.get("field_name") or "").strip()
        value = item.get("value")
        if not field_name or field_name in seen:
            continue
        if field_name not in allowed_fields:
            logger.warning("supplement_batch: drop_unknown_field=%s", field_name)
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        seen.add(field_name)
        out.append({"field_name": field_name, "value": value.strip()})
    return out


async def run_quick_supplement_batch(db: AsyncSession, req: Any) -> dict:
    """批量补全：一次 LLM 调用返回所有缺失字段的建议值。

    与逐条修复（run_qc_fix）的关系：
      - 同一套 QC_FIX 风格 prompt（鼓励 AI 根据上下文生成内容）
      - 一次返回 N 个 {field_name, value}
      - 前端按 field_name 用现有 FIELD_TO_LINE_PREFIX 机制行级写入
      - 跟逐条修复"写入病历"走完全相同的写入路径，不存在覆盖问题

    Args:
        req: SupplementRequest（含 qc_issues + 病历上下文 + 患者信息）

    Returns:
        {"items": [{"field_name": str, "value": str}, ...]}
        items 长度 ≤ qc_issues 长度（field_name 为空/重复/越界的会被丢弃）
    """
    qc_issues = list(getattr(req, "qc_issues", None) or [])
    issues_block, issue_count = _render_issues_block(qc_issues)
    if issue_count == 0:
        return {"items": []}

    # 允许的字段名白名单 = 入参清单里出现的所有 field_name（防 LLM 编造新名字）
    allowed_fields = {
        (it.get("field_name") or "").strip()
        for it in qc_issues
        if isinstance(it, dict) and (it.get("field_name") or "").strip()
        and not (it.get("field_name", "").startswith("__"))
    }

    current_record = (getattr(req, "current_content", "") or "").strip() or "（空）"
    # 截断超长正文，避免 prompt 过大（QC_FIX 模式 800 字符够 LLM 理解上下文）
    if len(current_record) > 4000:
        current_record = current_record[:4000] + "\n...（已截断）"

    prompt = safe_format(
        QC_FIX_BATCH_PROMPT,
        record_type=getattr(req, "record_type", "") or "outpatient",
        current_record=current_record,
        chief_complaint=getattr(req, "chief_complaint", "") or "未填写",
        history=getattr(req, "history_present_illness", "") or "未填写",
        issue_count=issue_count,
        issues_block=issues_block,
    )

    try:
        opts = await get_model_options(db, "qc")
        result = await llm_client.chat_json_stream(
            [{"role": "user", "content": prompt}],
            temperature=opts["temperature"],
            max_tokens=opts["max_tokens"],
            model_name=opts["model_name"],
        )
    except Exception as exc:
        logger.exception("supplement_batch: llm_failed err=%s", exc)
        return {"items": [], "error": f"AI 调用失败：{type(exc).__name__}"}

    # 写审计（不阻断主流程）
    try:
        usage = llm_client._last_usage
        await log_ai_task(
            "supplement_batch",
            token_input=usage.prompt_tokens if usage else 0,
            token_output=usage.completion_tokens if usage else 0,
        )
    except Exception as exc:
        logger.error("supplement_batch: log_failed err=%s", exc)

    items = _validate_items(
        result.get("items") if isinstance(result, dict) else None,
        allowed_fields,
    )

    # 数值真实性守卫（2026-06-11 治本）：prompt 红线是软约束，LLM 仍可能编造
    # "默认正常"生命体征。这里做确定性后校验：数值在医生录入数据里查无出处的
    # 体征 token 一律剔除（qc_issues 不算出处——它本身可能含 LLM 生成内容）
    source_text = "\n".join(
        str(v) for v in req.model_dump(exclude={"qc_issues"}).values() if v
    ) if hasattr(req, "model_dump") else (getattr(req, "current_content", "") or "")
    guarded: list[dict] = []
    for item in items:
        cleaned = strip_unsubstantiated_vitals(item["value"], source_text)
        if cleaned != item["value"]:
            logger.warning(
                "supplement_batch.guard: stripped_fabricated_vitals field=%s",
                item["field_name"],
            )
        if cleaned:
            guarded.append({"field_name": item["field_name"], "value": cleaned})
    items = guarded
    logger.info(
        "supplement_batch: done issues=%d returned=%d kept=%d",
        issue_count,
        len(result.get("items", [])) if isinstance(result, dict) else 0,
        len(items),
    )
    return {"items": items}
