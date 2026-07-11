"""住院评分规则 checker——首次病程录组（first_course_record 触发）

从 _inpatient_checkers.py 拆出：首次病程录相关的 3 条 checker + 守卫 helper。
行为、阈值、触发条件与原文件逐字一致，仅做物理拆分。
"""
from __future__ import annotations

from app.services.qc_engine.checker import RecordContext


# ─── 首次病程录（first_course_record 触发） ────────────────────


def _is_first_course(ctx: RecordContext) -> bool:
    return ctx.encounter_meta.record_type == "first_course_record"


def first_course_missing_case_summary(ctx: RecordContext) -> bool:
    """缺病例特点——PDF 单项否决"未归纳出病例特点"。"""
    if not _is_first_course(ctx):
        return False
    return not ctx.section("病例特点").is_filled()


def first_course_missing_diagnosis_discussion(ctx: RecordContext) -> bool:
    """缺拟诊讨论（含鉴别诊断分析）。"""
    if not _is_first_course(ctx):
        return False
    return not ctx.section("拟诊讨论").is_filled()


def first_course_missing_treatment_plan(ctx: RecordContext) -> bool:
    """缺诊疗计划。"""
    if not _is_first_course(ctx):
        return False
    return not ctx.section("诊疗计划").is_filled()
