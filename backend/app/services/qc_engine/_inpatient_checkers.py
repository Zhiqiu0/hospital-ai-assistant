"""住院评分规则 checker 函数库（_inpatient_checkers.py）

PDF 1:1 映射：浙江省住院病历质量检查评分表（2021 版）

为什么独立成文件：
  住院 rubric checker 数量多（20+ 个）+ 跨多个 record_type，
  跟 rubrics/zj_inpatient_2021.py 拆开方便单元测试 + 复用。

设计原则：
  每条 checker 第一行做 record_type 守卫——只在自己该跑的文档类型上触发，
  其他类型直接 return False 不扣分。这是"单 rubric 跑全 8 种住院 record_type"
  的核心：让 rubric 自适应医生当前在哪份文档质控。

可判定 / 不可判定边界：
  - 可判定：文本是否含某章节 / 字段是否填了 / 关键关键词是否出现
  - 不可判定（留 TODO）：
    * "严重违反诊疗规范"——LLM 才能判
    * "医师签名 / 时限内完成"——依赖审计日志
    * "复制现病史"——需跨文档比对（当前 ctx 单文档）
"""
from __future__ import annotations

from app.services.qc_engine.checker import RecordContext


# ─── 入院记录区（admission_note 触发） ─────────────────────────────


def _is_admission_note(ctx: RecordContext) -> bool:
    """守卫：仅 admission_note 触发本组规则。"""
    return ctx.encounter_meta.record_type == "admission_note"


def admission_missing_chief_complaint(ctx: RecordContext) -> bool:
    """缺主诉。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("主诉").is_filled()


def admission_chief_complaint_no_duration(ctx: RecordContext) -> bool:
    """主诉无持续时间——含"天/周/月/年/小时"等时间单位即视为合规。"""
    if not _is_admission_note(ctx):
        return False
    s = ctx.section("主诉")
    if not s.is_filled():
        return False  # 主诉本身缺由别的规则报
    return not any(unit in s.normalized for unit in ("天", "周", "月", "年", "小时", "分钟", "余"))


def admission_missing_present_illness(ctx: RecordContext) -> bool:
    """缺现病史。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("现病史").is_filled()


def admission_present_illness_no_general_condition(ctx: RecordContext) -> bool:
    """现病史缺一般情况（饮食/精神/睡眠/大小便）。"""
    if not _is_admission_note(ctx):
        return False
    s = ctx.section("现病史")
    if not s.is_filled():
        return False
    keywords = ("饮食", "精神", "睡眠", "大便", "小便", "二便", "纳眠", "纳食")
    return not any(s.contains(kw) for kw in keywords)


def admission_missing_past_history(ctx: RecordContext) -> bool:
    """缺既往史。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("既往史").is_filled()


def admission_missing_allergy_history(ctx: RecordContext) -> bool:
    """缺过敏史——PDF 既往史项里"缺食物、药物过敏史扣 2 分"。

    过敏史可能在【过敏史】独立章节或【既往史】里明确提到"过敏"。
    注意：既往史里"否认"通常是否认其他病史（如"否认高血压"），不一定是过敏史；
    所以只看"过敏"关键词，不放宽到"否认"，避免漏报。
    """
    if not _is_admission_note(ctx):
        return False
    if ctx.section("过敏史").is_filled():
        return False
    past = ctx.section("既往史")
    if past.is_filled() and "过敏" in past.normalized:
        return False
    return True


def admission_missing_personal_history(ctx: RecordContext) -> bool:
    """缺个人史。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("个人史").is_filled()


def admission_missing_marital_or_menstrual_history(ctx: RecordContext) -> bool:
    """缺婚育史或月经史——男性看婚育史，女性看月经史 + 婚育史。

    PDF："婚育史或月经史缺扣 1 分"——任一缺即扣（PDF "或"取严格读法）。
    简化：婚育史是必填（无论男女），月经史只在女性育龄期检查。
    """
    if not _is_admission_note(ctx):
        return False
    has_marital = ctx.section("婚育史").is_filled()
    if not has_marital:
        return True
    # 女性育龄期还要看月经史
    if ctx.patient_meta.is_female() and ctx.patient_meta.is_in_reproductive_age():
        if not ctx.section("月经史").is_filled():
            return True
    return False


def admission_missing_family_history(ctx: RecordContext) -> bool:
    """缺家族史。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("家族史").is_filled()


# ─── 专项评估 7 项（admission_note 触发） ─────────────────────────
#
# PDF "未评估扣 1 分/项"——本系统拆成 7 条独立 checker，每条 target_field
# 指向具体子字段（当前用药/疼痛评估/...），AI 批量补全 / 逐条修复
# 能针对性补到【专项评估】对应子行。
#
# 治本动机（2026-05-24）：旧设计 1 条规则打包 7 项 + target_field=
# "__special_assessment__" 引导去问诊面板，违反"病历正文是唯一编辑入口"。


def admission_missing_current_medications(ctx: RecordContext) -> bool:
    """缺当前用药评估。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("当前用药").is_filled()


def admission_missing_pain_assessment(ctx: RecordContext) -> bool:
    """缺疼痛评估（NRS 评分 0-10）。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("疼痛评估").is_filled()


def admission_missing_rehabilitation(ctx: RecordContext) -> bool:
    """缺康复需求评估。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("康复评估").is_filled()


def admission_missing_psychology(ctx: RecordContext) -> bool:
    """缺心理状态评估。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("心理评估").is_filled()


def admission_missing_nutrition(ctx: RecordContext) -> bool:
    """缺营养风险评估。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("营养评估").is_filled()


def admission_missing_vte_risk(ctx: RecordContext) -> bool:
    """缺 VTE 风险评估。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("VTE风险评估").is_filled()


def admission_missing_religion(ctx: RecordContext) -> bool:
    """缺宗教信仰/饮食禁忌评估。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("宗教信仰").is_filled()


def admission_missing_physical_exam(ctx: RecordContext) -> bool:
    """缺体格检查——生命体征 + 体检文字描述任一缺即扣。"""
    if not _is_admission_note(ctx):
        return False
    return not (ctx.section("体格检查").is_filled() or ctx.section("生命体征").is_filled())


def admission_missing_auxiliary_exam(ctx: RecordContext) -> bool:
    """缺辅助检查（入院前）。

    住院模板章节名是"辅助检查（入院前）"，但医生手填病历时可能简写为"辅助检查"；
    两种命名任一已填即合规——避免被章节标题命名细节误报。
    """
    if not _is_admission_note(ctx):
        return False
    return not (
        ctx.section("辅助检查（入院前）").is_filled()
        or ctx.section("辅助检查").is_filled()
    )


def admission_missing_diagnosis(ctx: RecordContext) -> bool:
    """缺入院诊断。"""
    if not _is_admission_note(ctx):
        return False
    return not ctx.section("入院诊断").is_filled()


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
