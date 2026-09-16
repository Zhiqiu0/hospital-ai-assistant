# -*- coding: utf-8 -*-
"""日常病程 / 上级查房记录的检查函数（2026-09-16 实装）。

背景：这两个大项（18 分 + 5 分）的 deduction_rules 自 2021 版 rubric 建立
以来一直为空，靠"评分仅供参考"披露兜底。本次按省 2021 版 PDF 把**客观
可判、零误报**的条款实装；主观条款（诊疗合理性、抗菌药物合规等）永远
需要人工检查，频次细档（病危每日一记）待病情等级口径确认——都不硬造
误报规则（本引擎零误报纪录不能破功）。

选取的判据与从宽边界（每处都对着 PDF 罚则原文）：
  · 内容空洞：只数 CJK 汉字（日期/数字/标点不计入），阈值 12 字——
    「患者今日无特殊。」7 字命中；「患者夜间安静入睡无特殊主诉」12 字
    不命中。任何认真写的最简病程都不会误伤。
  · 间隔超时：PDF"病情稳定至少每 3 天 1 次"是所有病情等级的最宽档——
    间隔超过它在任何等级下都违规，天然零误报。再加 12 小时宽限（同为
    "第 3 天"但钟点不同不算违规），阈值 84 小时。时间线含首程/日常病程/
    上级查房三类（查房记录亦属病程记录，PDF 明示可承接连续性）。
"""
from __future__ import annotations

import re
from datetime import timedelta

from app.services.qc_engine.checker import RecordContext

# 有效内容只数 CJK 汉字：日期行（2026-09-16 09:00）、数字、标点不计入，
# 防止"日期开头 + 一句空话"靠字符数混过阈值
_CJK_RE = re.compile(r"[一-鿿]")

# 内容空洞阈值（个汉字）。选 12 的依据见模块头注——从宽到不可能误伤
_MIN_CJK_CHARS = 12

# 间隔阈值：3 天（PDF 最宽档）+ 12 小时钟点宽限
_MAX_GAP = timedelta(hours=84)


def _cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text or ""))


def _course_too_brief(ctx: RecordContext) -> bool:
    """日常病程内容过简（PDF 罚则 2「未按规定常规记录病程扣 2 分/处」口径）。"""
    if ctx.encounter_meta.record_type != "course_record":
        return False
    return _cjk_count(ctx.record_text) < _MIN_CJK_CHARS


def _course_gap_exceeded(ctx: RecordContext) -> bool:
    """病程记录间隔超过 3 天（PDF 条款 2：病情稳定亦至少每 3 天 1 次）。

    仅在时间线已预取时检查（loaded=False 一律跳过——纯文本调用方/无
    encounter 上下文不误报）。相邻两条病程类文书的临床时点间隔超过
    84 小时即违规；多处超时也只按一条规则扣一次（scorer 语义，从宽）。
    """
    if ctx.encounter_meta.record_type != "course_record":
        return False
    tl = ctx.course_timeline
    if not tl.loaded or len(tl.recorded_ats) < 2:
        return False
    ordered = sorted(tl.recorded_ats)
    return any(
        (b - a) > _MAX_GAP for a, b in zip(ordered, ordered[1:])
    )


def _senior_round_too_brief(ctx: RecordContext) -> bool:
    """上级查房记录内容太简单（PDF 罚则 1 原文「查房记录内容太简单扣 1 分」）。"""
    if ctx.encounter_meta.record_type != "senior_round":
        return False
    return _cjk_count(ctx.record_text) < _MIN_CJK_CHARS
