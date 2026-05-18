"""浙江省中医门、急诊病历评分标准（rubrics/zj_outpatient_emergency_2023.py）

源文件：docs/浙江省中医门、急诊病历评分标准.pdf（定稿）

PDF 11 大项 1:1 映射，总分 100，PDF 注 5："90 分以下判定为不合格病历"。
门、急诊共用同一标准，第 11 项"其他（10 分）"为急诊专属补充评分。

修改本文件 = 修改法定标准 → 必须走 PR review + 法律合规复核。
"""
from __future__ import annotations

from app.services.qc_engine.checker import RecordContext
from app.services.qc_engine.rubric import (
    DeductionRule,
    GradeThreshold,
    Rubric,
    RubricItem,
)

# ─── checker 函数库（独立定义便于单测） ────────────────────────────

# ── 1. 基本要求（5 分） ──────────────────────────────────────────────


def _missing_visit_time_minute(ctx: RecordContext) -> bool:
    """急诊未具体到分钟（PDF 第 11 项要求；门诊不强制，仅急诊触发）。"""
    if not ctx.encounter_meta.is_emergency:
        return False
    # 病历正文里 "就诊时间" 行后跟的时间是否包含 ":" 分隔时分
    import re
    m = re.search(r"就诊时间[：:]\s*([^\n　]+)", ctx.record_text)
    if not m:
        return True
    time_str = m.group(1).strip()
    # 含 "HH:MM" 视为已具体到分钟
    return not re.search(r"\d{1,2}[:：]\d{2}", time_str)


# ── 2. 患者基础信息（10 分） ─────────────────────────────────────────

def _missing_patient_basic_info(ctx: RecordContext) -> bool:
    """患者基础信息（姓名、性别、年龄）缺项。

    C 方案治本（2026-05-19）：从 patient_meta 一等字段取，不再误查 inquiry。
    """
    return not ctx.patient_meta.has_basic_info()


def _missing_visit_time(ctx: RecordContext) -> bool:
    """无就诊时间——病历首行通常 "就诊时间：YYYY-MM-DD HH:MM"。"""
    import re
    return not re.search(r"就诊时间[：:]", ctx.record_text)


# ── 3. 主诉（5 分） ─────────────────────────────────────────────────

def _missing_chief_complaint(ctx: RecordContext) -> bool:
    return not ctx.section("主诉").is_filled()


def _missing_chief_complaint_duration(ctx: RecordContext) -> bool:
    """主诉持续时间未记录——含"天/周/月/年/小时"等时间单位关键词即视为有。"""
    if not ctx.section("主诉").is_filled():
        return False  # 主诉本身缺由别的规则报，不重复扣
    cc = ctx.section("主诉").normalized
    return not any(unit in cc for unit in ("天", "周", "月", "年", "小时", "分钟", "余"))


# ── 4. 现病史（20 分） ───────────────────────────────────────────────

def _missing_present_illness(ctx: RecordContext) -> bool:
    return not ctx.section("现病史").is_filled()


def _missing_present_illness_treatment(ctx: RecordContext) -> bool:
    """现病史缺诊治经过——未提及"治疗/服药/就诊/检查/用药"等关键词。"""
    s = ctx.section("现病史")
    if not s.is_filled():
        return False  # 缺现病史本身由别的规则报
    keywords = ("治疗", "服药", "就诊", "检查", "用药", "未治", "未予", "未行")
    return not any(s.contains(kw) for kw in keywords)


# ── 5. 既往史（10 分） ───────────────────────────────────────────────

def _missing_past_history(ctx: RecordContext) -> bool:
    return not ctx.section("既往史").is_filled()


def _missing_menstrual_history_for_female(ctx: RecordContext) -> bool:
    """育龄期女性无月经史扣 5 分（PDF）。

    判定育龄期：性别为女且年龄在 12-55 之间——粗略阈值，避免漏报。

    C 方案治本（2026-05-19）：性别 + 年龄都从 patient_meta 取（旧实现 age
    误查 inquiry 字典导致永远拿不到值 → 此规则从不触发）。
    """
    if not ctx.patient_meta.is_female():
        return False
    if not ctx.patient_meta.is_in_reproductive_age():
        return False
    # 月经史可能在【既往史】内或独立【月经史】章节
    if ctx.section("月经史").is_filled():
        return False
    past = ctx.section("既往史")
    if past.is_filled() and "经" in past.normalized:
        return False
    return True


# ── 6. 体格检查（10 分） ─────────────────────────────────────────────

def _missing_tcm_four_diagnoses(ctx: RecordContext) -> bool:
    """缺中医四诊扣 10 分——望/闻/切（舌+脉）四项至少要有舌脉。"""
    return not (ctx.section("舌象").is_filled() and ctx.section("脉象").is_filled())


# ── 7. 辅助检查（5 分） ──────────────────────────────────────────────

def _missing_auxiliary_exam(ctx: RecordContext) -> bool:
    """辅助检查记录缺失——'暂无' / '无' 视为已记录（医生选择不做也是规范）。"""
    s = ctx.section("辅助检查")
    return not s.is_filled()


# ── 8. 诊断（10 分） ────────────────────────────────────────────────

def _missing_tcm_diagnosis(ctx: RecordContext) -> bool:
    """中医诊断缺失（疾病诊断 + 证候诊断至少有疾病诊断）。

    PDF："有中医治疗的病历无中医诊断扣 10 分"——这里宽松判定为"无中医疾病诊断扣"。
    """
    return not ctx.section("中医疾病诊断").is_filled()


def _incomplete_tcm_diagnosis(ctx: RecordContext) -> bool:
    """中医诊断不全扣 2 分（疾病 + 证候 缺其一）。"""
    has_disease = ctx.section("中医疾病诊断").is_filled()
    has_syndrome = ctx.section("中医证候诊断").is_filled()
    # 只在"至少有一项"时才触发不全（两项都缺由 _missing_tcm_diagnosis 报）
    return (has_disease ^ has_syndrome)


def _missing_western_diagnosis(ctx: RecordContext) -> bool:
    """西医诊断缺失（PDF 要求"规范书写中、西医诊断"）。"""
    return not ctx.section("西医诊断").is_filled()


# ── 9. 治疗意见及措施（10 分） ───────────────────────────────────────

def _missing_treatment_plan(ctx: RecordContext) -> bool:
    """检查治疗项目不明确——处理意见为空即视为不明确。"""
    return not ctx.section("处理意见").is_filled()


def _missing_followup_advice(ctx: RecordContext) -> bool:
    """无复诊建议或注意事项——两者都缺才扣（任一有即合规）。"""
    return not (
        ctx.section("复诊建议").is_filled() or ctx.section("注意事项").is_filled()
    )


def _missing_treatment_method(ctx: RecordContext) -> bool:
    """治则治法缺失——中医治疗规范要求"辨证施治"，应有治则治法。"""
    return not ctx.section("治则治法").is_filled()


# ── 11. 其他（10 分，急诊专属补充） ─────────────────────────────────

def _emergency_missing_vitals(ctx: RecordContext) -> bool:
    """急诊病人无 T、P、R、BP 生命体征记录扣 2 分。"""
    if not ctx.encounter_meta.is_emergency:
        return False
    return not ctx.section("生命体征").is_filled()


def _emergency_missing_disposition(ctx: RecordContext) -> bool:
    """急诊患者去向未记录扣 2 分。"""
    if not ctx.encounter_meta.is_emergency:
        return False
    return not ctx.section("患者去向").is_filled()


# ─── 11 大项构造（PDF 1:1 映射） ────────────────────────────────────

_BASIC_REQUIREMENTS = RubricItem(
    name="基本要求",
    max_points=5,
    description="病历书写规范使用医学术语；接诊医师及时完成；日期时间规范；阿拉伯数字 + 24 小时制",
    deduction_rules=(
        # PDF "未及时完成扣 5 分"——当前数据层难判定"是否及时"，留待后续接入审计日志
        # （当前不实现该规则；规则可加但不出发反而是 lenient 的正确选择）
    ),
)

_PATIENT_BASIC_INFO = RubricItem(
    name="患者基础信息",
    max_points=10,
    description="姓名/性别/出生年月日/民族/婚姻/职业/住址/药物过敏史 + 就诊科室时间",
    deduction_rules=(
        DeductionRule(
            code="OP-BASIC-INFO-01",
            description="患者基础信息缺项（姓名/性别/年龄）",
            deduct_points=1,
            checker=_missing_patient_basic_info,
        ),
        DeductionRule(
            code="OP-BASIC-INFO-02",
            description="无就诊时间",
            deduct_points=2,
            checker=_missing_visit_time,
        ),
    ),
)

_CHIEF_COMPLAINT = RubricItem(
    name="主诉",
    max_points=5,
    description="初诊记录主要症状、体征及持续时间；复诊可用诊断代替",
    deduction_rules=(
        DeductionRule(
            code="OP-CHIEF-COMPLAINT-01",
            description="主诉缺失或主要症状、体征记录不规范",
            deduct_points=2,
            checker=_missing_chief_complaint,
        ),
        DeductionRule(
            code="OP-CHIEF-COMPLAINT-02",
            description="主诉持续时间未记录",
            deduct_points=2,
            checker=_missing_chief_complaint_duration,
        ),
    ),
)

_PRESENT_ILLNESS = RubricItem(
    name="现病史",
    max_points=20,
    description="记录本次起病的主要症状/体征 + 发病以来诊治经过及结果",
    deduction_rules=(
        DeductionRule(
            code="OP-PRESENT-ILLNESS-01",
            description="现病史缺失或主要症状、体征描述不清",
            deduct_points=5,
            checker=_missing_present_illness,
        ),
        DeductionRule(
            code="OP-PRESENT-ILLNESS-02",
            description="缺诊治经过",
            deduct_points=2,
            checker=_missing_present_illness_treatment,
        ),
    ),
)

_PAST_HISTORY = RubricItem(
    name="既往史",
    max_points=10,
    description="既往病史/传染病史/手术史/月经史/生育史/家族史/长期用药史",
    deduction_rules=(
        DeductionRule(
            code="OP-PAST-HISTORY-01",
            description="既往史缺失",
            deduct_points=2,
            checker=_missing_past_history,
        ),
        DeductionRule(
            code="OP-PAST-HISTORY-02",
            description="育龄期女性无月经史",
            deduct_points=5,
            checker=_missing_menstrual_history_for_female,
        ),
    ),
)

_PHYSICAL_EXAM = RubricItem(
    name="体格检查",
    max_points=10,
    description="按中医四诊要求记录重要的阳性体征及必要的阴性体征舌脉象",
    deduction_rules=(
        DeductionRule(
            code="OP-PHYSICAL-EXAM-01",
            description="缺中医四诊（舌象/脉象）",
            deduct_points=10,
            checker=_missing_tcm_four_diagnoses,
        ),
    ),
)

_AUXILIARY_EXAM = RubricItem(
    name="辅助检查及结果",
    max_points=5,
    description="应记录重要的辅助检查结果",
    deduction_rules=(
        DeductionRule(
            code="OP-AUXILIARY-EXAM-01",
            description="辅助检查未记录",
            deduct_points=5,
            checker=_missing_auxiliary_exam,
        ),
    ),
)

_DIAGNOSIS = RubricItem(
    name="诊断",
    max_points=10,
    description="规范书写中、西医诊断；中医诊断包括疾病诊断与证候诊断",
    deduction_rules=(
        DeductionRule(
            code="OP-DIAGNOSIS-01",
            description="有中医治疗的病历无中医诊断",
            deduct_points=10,
            checker=_missing_tcm_diagnosis,
        ),
        DeductionRule(
            code="OP-DIAGNOSIS-02",
            description="中医诊断不全（疾病诊断/证候诊断 缺其一）",
            deduct_points=2,
            checker=_incomplete_tcm_diagnosis,
        ),
        DeductionRule(
            code="OP-DIAGNOSIS-03",
            description="西医诊断缺失",
            deduct_points=2,
            checker=_missing_western_diagnosis,
        ),
    ),
)

_TREATMENT = RubricItem(
    name="治疗意见及措施",
    max_points=10,
    description="检查治疗项目明确规范；中医辨证论治；有复诊建议及注意事项",
    deduction_rules=(
        DeductionRule(
            code="OP-TREATMENT-01",
            description="检查治疗项目不明确（处理意见缺失）",
            deduct_points=5,
            checker=_missing_treatment_plan,
        ),
        DeductionRule(
            code="OP-TREATMENT-02",
            description="治则治法与证型不符（治则治法缺失）",
            deduct_points=5,
            checker=_missing_treatment_method,
        ),
        DeductionRule(
            code="OP-TREATMENT-03",
            description="无复诊建议或注意事项",
            deduct_points=5,
            checker=_missing_followup_advice,
        ),
    ),
)

# 第 10 项"知情同意书 5 分"——当前系统暂无知情同意签署字段，整项规则待后续接入
# 该字段的录入页面后再补；这一项暂为空 rules（满分扣 0）
_INFORMED_CONSENT = RubricItem(
    name="知情同意书",
    max_points=5,
    description="需取得患者书面同意方可进行的医疗活动须签署知情同意书",
    deduction_rules=(
        # 待补：知情同意书数据当前未录入系统，新增字段后再加 checker
        # PR review 时显式空 rules 留作占位（满分计算包含该项 5 分）
    ),
)

_OTHER_EMERGENCY = RubricItem(
    name="其他（急诊补充）",
    max_points=10,
    description="急诊时间具体到分钟；T/P/R/BP 生命体征；留观/患者去向；中医四诊；抢救记录",
    deduction_rules=(
        DeductionRule(
            code="OP-OTHER-01",
            description="急诊就诊时间未具体到分钟",
            deduct_points=5,
            checker=_missing_visit_time_minute,
        ),
        DeductionRule(
            code="OP-OTHER-02",
            description="急诊病人无 T、P、R、BP 生命体征记录",
            deduct_points=2,
            checker=_emergency_missing_vitals,
        ),
        DeductionRule(
            code="OP-OTHER-03",
            description="急诊患者去向未记录",
            deduct_points=2,
            checker=_emergency_missing_disposition,
        ),
    ),
)


# ─── 完整 Rubric 对象 ────────────────────────────────────────────────

ZJ_OUTPATIENT_EMERGENCY_V2023 = Rubric(
    name="浙江省中医门、急诊病历评分标准",
    version="2023",
    record_scope="single",
    items=(
        _BASIC_REQUIREMENTS,
        _PATIENT_BASIC_INFO,
        _CHIEF_COMPLAINT,
        _PRESENT_ILLNESS,
        _PAST_HISTORY,
        _PHYSICAL_EXAM,
        _AUXILIARY_EXAM,
        _DIAGNOSIS,
        _TREATMENT,
        _INFORMED_CONSENT,
        _OTHER_EMERGENCY,
    ),
    grade_thresholds=(
        # PDF 注 5："90 分以下判定为不合格病历"——只分两级
        GradeThreshold(min_score=90, label="合格"),
        GradeThreshold(min_score=0, label="不合格"),
    ),
)

# 单元测试 / 评分器入口断言：总分必须等于 100（PDF 整张表合计）
assert ZJ_OUTPATIENT_EMERGENCY_V2023.total_points == 100, \
    f"门急诊评分表总分应为 100，当前为 {ZJ_OUTPATIENT_EMERGENCY_V2023.total_points}"
