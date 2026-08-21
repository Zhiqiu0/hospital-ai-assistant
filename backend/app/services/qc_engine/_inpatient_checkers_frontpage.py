# -*- coding: utf-8 -*-
"""病案首页区 checker（qc_engine/_inpatient_checkers_frontpage.py，2026-08-21 阶段3）。

对应 PDF"病案首页 10 分"评分说明的**可确定性判定子集**（法定 1:1 铁律：
只实装能从结构化数据确定判真的条款，判不了的绝不猜）：

  PDF 1. 患者基本信息错误（姓名、性别、身份证号码等）→ 单项否决
         可判定：身份证校验位错误 / 身份证性别位·出生段与档案矛盾
        （姓名对错无从判——只判"自相矛盾"这种确定错误）
  PDF 2. 主要诊断填写或编码错误 → 单项否决
         可判定：结构化条目存在但无主诊断标记（缺失=填写错误的确定情形）
         编码错误：PDF 注明"考核医师病历质量时，编码不做要求"→ 不扣分
  PDF 4. 项目填写错误或漏填 扣 1 分/处
         可判定：入院病情标志缺失（诊断条目级）、入院途径缺失、药物过敏未填
        （损伤中毒/离院方式/31天再住院/昏迷时间系统无字段——不判不猜）
  PDF 5. 其余信息错误或漏填 扣 0.5 分/处
         可判定：血型未填
  PDF 3（手术/操作）、PDF 6（出院后24h完成）——手术无结构化、首页填报时刻
  在 HIS 侧，均判不了 → 跳过。

触发口径：
  - front_page.loaded=False（service 未预取）→ 一律不触发（兼容纯文本调用）
  - record_type 守卫：admission_note（入院时把关）/ discharge_record（出院前最后把关）
  - DeductionRule checker 是布尔——"1分/处"按保守口径触发一次扣一次
    （不虚报多处；宁少扣不多扣，注释向 PDF 负责）
"""
import re

from app.services.qc_engine.checker import RecordContext

# 首页规则只在这两类文书上触发（入院把关 + 出院前最后把关）
_FRONT_PAGE_RECORD_TYPES = ("admission_note", "discharge_record")

_ID_CARD_WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
_ID_CARD_CHECKS = "10X98765432"


def _applicable(ctx: RecordContext) -> bool:
    return (
        ctx.front_page.loaded
        and ctx.encounter_meta.record_type in _FRONT_PAGE_RECORD_TYPES
    )


def _id_card_valid(id_card: str) -> bool:
    """18 位身份证校验位验证（GB 11643）。"""
    if not re.fullmatch(r"\d{17}[\dXx]", id_card):
        return False
    total = sum(int(id_card[i]) * _ID_CARD_WEIGHTS[i] for i in range(17))
    return _ID_CARD_CHECKS[total % 11] == id_card[17].upper()


def frontpage_basic_info_conflict(ctx: RecordContext) -> bool:
    """基本信息确定性错误（veto）：身份证校验位错 / 性别位·出生段与档案矛盾。"""
    if not _applicable(ctx):
        return False
    idc = (ctx.front_page.id_card or "").strip()
    if not idc:
        return False  # 未录身份证不算"错误"（漏填走别的口径，且门诊常无）
    if not _id_card_valid(idc):
        return True
    # 性别位（第 17 位）：奇=男 偶=女
    gender = (ctx.front_page.gender or "").lower()
    if gender in ("male", "female", "男", "女"):
        is_male = gender in ("male", "男")
        if (int(idc[16]) % 2 == 1) != is_male:
            return True
    # 出生段（7-14 位）与档案出生日期矛盾
    birth = (ctx.front_page.birth_date or "")[:10].replace("-", "")
    if len(birth) == 8 and idc[6:14] != birth:
        return True
    return False


def frontpage_primary_diagnosis_missing(ctx: RecordContext) -> bool:
    """主要诊断缺失（veto）：有结构化条目但无一条 is_primary，或条目为空。"""
    if not _applicable(ctx):
        return False
    dx = ctx.front_page.diagnoses
    if not dx:
        return True  # 住院病案无任何诊断条目——主诊断必然缺失
    return not any(d.get("is_primary") for d in dx)


def frontpage_admission_condition_missing(ctx: RecordContext) -> bool:
    """入院病情标志缺失（项目漏填 1 分口径）：存在缺标志的诊断条目。

    仅判西医与中医疾病条目（证候是辨证结论，首页"入院病情"针对疾病诊断）。
    """
    if not _applicable(ctx):
        return False
    return any(
        not (d.get("admission_condition") or "").strip()
        for d in ctx.front_page.diagnoses
        if d.get("category") in ("western", "tcm_disease")
    )


def frontpage_admission_route_missing(ctx: RecordContext) -> bool:
    """入院途径缺失（项目漏填 1 分口径）。"""
    if not _applicable(ctx):
        return False
    return not (ctx.front_page.admission_route or "").strip()


def frontpage_allergy_missing(ctx: RecordContext) -> bool:
    """药物过敏未填（项目漏填 1 分口径）——"否认过敏"是有效填写，空才算漏。"""
    if not _applicable(ctx):
        return False
    return not (ctx.front_page.allergy_history or "").strip()


def frontpage_blood_type_missing(ctx: RecordContext) -> bool:
    """血型未填（其余信息 0.5 分口径）。"""
    if not _applicable(ctx):
        return False
    return not (ctx.front_page.blood_type or "").strip()
