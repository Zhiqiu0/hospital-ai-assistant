"""住院评分规则 checker——围手术期组
（pre_op_summary / op_record / post_op_record 触发）

从 _inpatient_checkers.py 拆出：围手术期相关的 4 条 checker + 守卫 helper。
行为、阈值、触发条件与原文件逐字一致，仅做物理拆分。
"""
from __future__ import annotations

from app.services.qc_engine.checker import RecordContext


# ─── 围手术期（pre_op_summary / op_record / post_op_record 触发） ────


def _is_perioperative(ctx: RecordContext) -> bool:
    return ctx.encounter_meta.record_type in (
        "pre_op_summary",
        "op_record",
        "post_op_record",
    )


def perioperative_pre_op_missing_indication(ctx: RecordContext) -> bool:
    """术前小结缺手术指征。"""
    if ctx.encounter_meta.record_type != "pre_op_summary":
        return False
    return not ctx.section("手术指征").is_filled()


def perioperative_pre_op_missing_plan(ctx: RecordContext) -> bool:
    """术前小结缺拟施手术名称及方式。"""
    if ctx.encounter_meta.record_type != "pre_op_summary":
        return False
    return not ctx.section("拟施手术名称及方式").is_filled()


def perioperative_op_record_missing_process(ctx: RecordContext) -> bool:
    """手术记录缺手术经过——PDF 单项否决"缺手术记录"。"""
    if ctx.encounter_meta.record_type != "op_record":
        return False
    return not ctx.section("手术经过").is_filled()


def perioperative_post_op_missing_recovery(ctx: RecordContext) -> bool:
    """术后病程缺病情分析及术后恢复情况评估。"""
    if ctx.encounter_meta.record_type != "post_op_record":
        return False
    return not ctx.section("病情分析及术后恢复情况评估").is_filled()
