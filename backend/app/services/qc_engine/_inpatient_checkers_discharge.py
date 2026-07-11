"""住院评分规则 checker——出院（死亡）记录组（discharge_record 触发）

从 _inpatient_checkers.py 拆出：出院记录相关的 5 条 checker + 守卫 helper。
行为、阈值、触发条件与原文件逐字一致，仅做物理拆分。
"""
from __future__ import annotations

from app.services.qc_engine.checker import RecordContext


# ─── 出院（死亡）记录（discharge_record 触发） ──────────────────


def _is_discharge(ctx: RecordContext) -> bool:
    return ctx.encounter_meta.record_type == "discharge_record"


def discharge_missing_admission_status(ctx: RecordContext) -> bool:
    """缺入院情况。"""
    if not _is_discharge(ctx):
        return False
    return not ctx.section("入院情况").is_filled()


def discharge_missing_treatment_course(ctx: RecordContext) -> bool:
    """缺诊疗经过。"""
    if not _is_discharge(ctx):
        return False
    return not ctx.section("诊疗经过").is_filled()


def discharge_missing_discharge_diagnosis(ctx: RecordContext) -> bool:
    """缺出院诊断。"""
    if not _is_discharge(ctx):
        return False
    return not ctx.section("出院诊断").is_filled()


def discharge_missing_discharge_advice(ctx: RecordContext) -> bool:
    """缺出院医嘱。"""
    if not _is_discharge(ctx):
        return False
    return not ctx.section("出院医嘱").is_filled()


def discharge_missing_discharge_status(ctx: RecordContext) -> bool:
    """缺出院情况——PDF 单项否决（关键字段缺失视为出院记录不完整）。"""
    if not _is_discharge(ctx):
        return False
    return not ctx.section("出院情况").is_filled()
