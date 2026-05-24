"""浙江省中医住院病历评分标准（rubrics/zj_inpatient_2021.py）

源文件：docs/浙江省中医住院病历评分标准.pdf（2021 版定稿）

设计选择（2026-05-19 落地）：
  PDF 总分 100，分散在 8 大区（病案首页 / 入院记录 / 病程 / 围手术期 / 出院 /
  知情同意 / 会诊 / 医嘱 / 书写基本要求），其中 5 区不在病历正文里（病案首页是
  独立结构数据、知情同意是 PDF 表单、会诊/医嘱/书写要求依赖审计层）——本系统
  暂不评分，但保留 RubricItem 占位让总分仍 = 100、等级阈值（甲/乙/丙）正常工作。

  跨 record_type 适配：单份 Rubric 跑全部 8 种住院 record_type，每条 checker 第一行
  做 record_type 守卫——admission_note 跑入院记录区规则、first_course_record 跑首
  次病程规则、discharge_record 跑出院规则…… 不适用的规则不触发，不扣分。

  分数语义：医生质控 admission_note 时只触发入院记录区规则（max 24 分扣分），
  分数 = 100 - 扣分（其他大项保持满分）。这跟 PDF "整套住院流程综合评分" 的初衷
  有偏差，但能给出"当前文档质量"的合理评估，且 UI 总分 100 跟门急诊一致。

修改本文件 = 修改法定标准 → 必须走 PR review + 法律合规复核。

PDF 备注 8："90 分以下为乙级病历，80 分以下为丙级病历"。
PDF 备注 6："单项否决指标计分时扣 10 分，不累积扣分"。
"""
from __future__ import annotations

from app.services.qc_engine import _inpatient_checkers as ic
from app.services.qc_engine.rubric import (
    DeductionRule,
    GradeThreshold,
    Rubric,
    RubricItem,
    VetoRule,
)


# ─── 1. 病案首页（10 分）— 暂不评分，占位 ─────────────────────────
# PDF：患者基本信息错误（单项否决）、主要诊断错误（单项否决）…… 都是面向
# 结构化首页数据，不在病历正文 ctx 范围内。本系统暂留空规则，待接入病案首页
# 数据后实装。
_FRONT_PAGE = RubricItem(
    name="病案首页",
    max_points=10,
    description="患者基本信息/诊断/手术编码/入院途径等首页字段（本系统暂不评分）",
    deduction_rules=(),  # TODO: 接入结构化首页数据后实装
)


# ─── 2. 入院记录·主诉（2 分） ──────────────────────────────────────
_ADMISSION_CHIEF_COMPLAINT = RubricItem(
    name="入院记录·主诉",
    max_points=2,
    description="简明扼要，能导出第一诊断；原则不用诊断名称",
    deduction_rules=(
        DeductionRule(
            code="IP-ADMISSION-CHIEF-01",
            description="主诉缺失或主要症状未写",
            deduct_points=1,
            checker=ic.admission_missing_chief_complaint,
            target_field="主诉",
        ),
        DeductionRule(
            code="IP-ADMISSION-CHIEF-02",
            description="主诉持续时间不准确或缺近况描述",
            deduct_points=0.5,
            checker=ic.admission_chief_complaint_no_duration,
            target_field="主诉",
        ),
    ),
)


# ─── 3. 入院记录·现病史（6 分） ────────────────────────────────────
_ADMISSION_PRESENT_ILLNESS = RubricItem(
    name="入院记录·现病史",
    max_points=6,
    description="发病情况/症状特点/诊治经过/一般情况",
    deduction_rules=(
        DeductionRule(
            code="IP-ADMISSION-PI-01",
            description="现病史缺失",
            deduct_points=3,
            checker=ic.admission_missing_present_illness,
            target_field="现病史",
        ),
        DeductionRule(
            code="IP-ADMISSION-PI-02",
            description="缺一般情况描述（饮食/精神/睡眠/大小便）",
            deduct_points=0.5,
            checker=ic.admission_present_illness_no_general_condition,
            target_field="现病史",
        ),
    ),
)


# ─── 4. 入院记录·既往史（2 分） ────────────────────────────────────
_ADMISSION_PAST_HISTORY = RubricItem(
    name="入院记录·既往史",
    max_points=2,
    description="既往疾病史/食物药物过敏史/手术外伤/输血等",
    deduction_rules=(
        DeductionRule(
            code="IP-ADMISSION-PAST-01",
            description="既往史缺失",
            deduct_points=0.5,
            checker=ic.admission_missing_past_history,
            target_field="既往史",
        ),
        DeductionRule(
            code="IP-ADMISSION-PAST-02",
            description="缺食物、药物过敏史",
            deduct_points=2,
            checker=ic.admission_missing_allergy_history,
            target_field="过敏史",
        ),
    ),
)


# ─── 5. 入院记录·个人/婚育/月经/家族史（3 分） ─────────────────
_ADMISSION_SOCIAL_HISTORY = RubricItem(
    name="入院记录·个人婚育月经家族史",
    max_points=3,
    description="个人史 + 婚育/月经史 + 家族史",
    deduction_rules=(
        DeductionRule(
            code="IP-ADMISSION-SOCIAL-01",
            description="个人史缺失",
            deduct_points=1,
            checker=ic.admission_missing_personal_history,
            target_field="个人史",
        ),
        DeductionRule(
            code="IP-ADMISSION-SOCIAL-02",
            description="婚育史或月经史缺失",
            deduct_points=1,
            # 缺婚育史 → 写婚育史；缺月经史 → 月经史。这里默认指向婚育史
            # （女性育龄期月经史缺失场景下医生应额外补月经史）。
            checker=ic.admission_missing_marital_or_menstrual_history,
            target_field="婚育史",
        ),
        DeductionRule(
            code="IP-ADMISSION-SOCIAL-03",
            description="家族史缺或未描述父母情况",
            deduct_points=1,
            checker=ic.admission_missing_family_history,
            target_field="家族史",
        ),
    ),
)


# ─── 6. 入院记录·专项评估（3 分） ──────────────────────────────────
#
# PDF "未评估扣 1 分/项"——拆成 7 条独立规则，每条扣 1 分；
# max_points=3 由 RubricItem 上限保护，扣分超 3 时仅扣 3（PDF 项上限语义）。
# 治本动机（2026-05-24）：旧设计 1 条规则打包 7 项 + target_field 错配
# 引导去问诊面板，违反"病历正文是唯一编辑入口"。新设计每条 target_field
# 指向具体子字段，AI 补全/逐条修复都能正确写入【专项评估】对应子行。
_ADMISSION_SPECIAL_ASSESSMENT = RubricItem(
    name="入院记录·专项评估",
    max_points=3,
    description="评估患者当前用药、疼痛、康复、心理、营养、VTE 风险及宗教信仰",
    deduction_rules=(
        DeductionRule(
            code="IP-ADMISSION-ASSESS-01",
            description="缺当前用药评估",
            deduct_points=1,
            checker=ic.admission_missing_current_medications,
            target_field="当前用药",
        ),
        DeductionRule(
            code="IP-ADMISSION-ASSESS-02",
            description="缺疼痛评估（NRS 0-10）",
            deduct_points=1,
            checker=ic.admission_missing_pain_assessment,
            target_field="疼痛评估",
        ),
        DeductionRule(
            code="IP-ADMISSION-ASSESS-03",
            description="缺康复需求评估",
            deduct_points=1,
            checker=ic.admission_missing_rehabilitation,
            target_field="康复评估",
        ),
        DeductionRule(
            code="IP-ADMISSION-ASSESS-04",
            description="缺心理状态评估",
            deduct_points=1,
            checker=ic.admission_missing_psychology,
            target_field="心理评估",
        ),
        DeductionRule(
            code="IP-ADMISSION-ASSESS-05",
            description="缺营养风险评估",
            deduct_points=1,
            checker=ic.admission_missing_nutrition,
            target_field="营养评估",
        ),
        DeductionRule(
            code="IP-ADMISSION-ASSESS-06",
            description="缺 VTE 风险评估",
            deduct_points=1,
            checker=ic.admission_missing_vte_risk,
            target_field="VTE风险评估",
        ),
        DeductionRule(
            code="IP-ADMISSION-ASSESS-07",
            description="缺宗教信仰/饮食禁忌评估",
            deduct_points=1,
            checker=ic.admission_missing_religion,
            target_field="宗教信仰",
        ),
    ),
)


# ─── 7. 入院记录·体格检查（2 分） ──────────────────────────────────
_ADMISSION_PHYSICAL_EXAM = RubricItem(
    name="入院记录·体格检查",
    max_points=2,
    description="体检表项目完整 + 专科检查 + 鉴别诊断相关体征",
    deduction_rules=(
        DeductionRule(
            code="IP-ADMISSION-EXAM-01",
            description="缺体格检查",
            deduct_points=1,
            checker=ic.admission_missing_physical_exam,
            target_field="体格检查",
        ),
    ),
)


# ─── 8. 入院记录·辅助检查（2 分） ──────────────────────────────────
_ADMISSION_AUXILIARY_EXAM = RubricItem(
    name="入院记录·辅助检查",
    max_points=2,
    description="记录入院前所作的与本次疾病相关的主要检查及其结果",
    deduction_rules=(
        DeductionRule(
            code="IP-ADMISSION-AUX-01",
            description="未记录辅助检查与结果",
            deduct_points=1,
            checker=ic.admission_missing_auxiliary_exam,
            target_field="辅助检查",
        ),
    ),
)


# ─── 9. 入院记录·诊断（4 分） ──────────────────────────────────────
_ADMISSION_DIAGNOSIS = RubricItem(
    name="入院记录·诊断",
    max_points=4,
    description="诊断书写准确，初步诊断合理全面",
    deduction_rules=(
        DeductionRule(
            code="IP-ADMISSION-DIAG-01",
            description="入院诊断缺失",
            deduct_points=2,
            checker=ic.admission_missing_diagnosis,
            target_field="入院诊断",
        ),
    ),
)


# ─── 10. 首次病程录（6 分） ────────────────────────────────────────
# PDF "未归纳出病例特点单项否决"——实装为 VetoRule
_FIRST_COURSE_RECORD = RubricItem(
    name="首次病程录",
    max_points=6,
    description="入院 8 小时内完成；病例特点 + 拟诊讨论 + 诊疗计划",
    deduction_rules=(
        DeductionRule(
            code="IP-FIRST-COURSE-01",
            description="拟诊讨论缺失（鉴别诊断未写）",
            deduct_points=1,
            checker=ic.first_course_missing_diagnosis_discussion,
            target_field="拟诊讨论",
        ),
        DeductionRule(
            code="IP-FIRST-COURSE-02",
            description="诊疗计划不全（检查/治疗措施不具体）",
            deduct_points=0.5,
            checker=ic.first_course_missing_treatment_plan,
            target_field="诊疗计划",
        ),
    ),
    veto_rules=(
        VetoRule(
            code="IP-FIRST-COURSE-VETO-01",
            description="未归纳出病例特点（单项否决）",
            checker=ic.first_course_missing_case_summary,
            target_field="病例特点",
        ),
    ),
)


# ─── 11. 上级医师查房记录（5 分）— 暂留占位 ─────────────────
# PDF 主要扣分项依赖审计层：
#   - "主治以上首次查房未在 48 小时内完成扣 5 分"——需时间戳
#   - "缺副高以上医师查房记录单项否决"——需医师职称数据
#   - "查房记录未签名扣 1 分"——需签名审计
# 文本能判定的只有"上级医师查房记录章节是否存在"，跟"未在 48 小时完成"
# 不等价，暂留空规则。
_SENIOR_ROUND = RubricItem(
    name="上级医师查房记录",
    max_points=5,
    description="主治以上首次查房 48 小时内完成；副高每周 2 次；危重必查（本系统暂不评分）",
    deduction_rules=(),  # TODO: 接入审计日志后实装时限/签名 veto
)


# ─── 12. 日常病程记录（18 分）— 暂留占位 ────────────────────
# PDF 18 分含 12 条扣分点 + 多条单项否决，绝大多数需要审计层数据
# （时限/签名/医嘱/抢救/输血等）或合理性判断（LLM 才能判）。
# 文本能判定的"日常病程记录章节存在性"语义太弱（即使存在也不一定按规要求），
# 暂全留空，待审计层接入后再补。
_COURSE_RECORD = RubricItem(
    name="日常病程记录",
    max_points=18,
    description="病程书写规范/抗菌药物/抢救记录/危急值/输血等（本系统暂不评分）",
    deduction_rules=(),  # TODO: 接入审计 + LLM 合理性判断后实装
)


# ─── 13. 围手术期相关记录（12 分） ──────────────────────────────
# 文本可判定：术前小结/手术记录/术后病程的关键章节是否存在
# 不可判定（留 TODO）：术前讨论参与者、麻醉记录、手术风险评估三方签字等
_PERIOPERATIVE = RubricItem(
    name="围手术期相关记录",
    max_points=12,
    description="术前小结/麻醉记录/手术记录/术后首次病程/术后查房",
    deduction_rules=(
        DeductionRule(
            code="IP-PERIOP-PRE-01",
            description="术前小结缺手术指征",
            deduct_points=1,
            checker=ic.perioperative_pre_op_missing_indication,
            target_field="手术指征",
        ),
        DeductionRule(
            code="IP-PERIOP-PRE-02",
            description="术前小结缺拟施手术名称及方式",
            deduct_points=1,
            checker=ic.perioperative_pre_op_missing_plan,
            target_field="拟施手术名称及方式",
        ),
        DeductionRule(
            code="IP-PERIOP-POST-01",
            description="术后病程缺病情分析及术后恢复情况评估",
            deduct_points=1,
            checker=ic.perioperative_post_op_missing_recovery,
            target_field="病情分析及术后恢复情况评估",
        ),
    ),
    veto_rules=(
        VetoRule(
            code="IP-PERIOP-VETO-01",
            description="缺手术记录·手术经过（单项否决）",
            checker=ic.perioperative_op_record_missing_process,
            target_field="手术经过",
        ),
    ),
)


# ─── 14. 出院（死亡）记录（5 分） ──────────────────────────────────
# PDF "出院记录未在 24 小时内完成单项否决"——文本无法判定时限。
# 文本可判定的核心字段：入院情况/诊疗经过/出院情况/出院诊断/出院医嘱
_DISCHARGE_RECORD = RubricItem(
    name="出院（死亡）记录",
    max_points=5,
    description="主诉/入院情况/入院诊断/诊疗经过/出院情况/出院诊断/出院医嘱",
    deduction_rules=(
        DeductionRule(
            code="IP-DISCHARGE-01",
            description="缺入院情况",
            deduct_points=1,
            checker=ic.discharge_missing_admission_status,
            target_field="入院情况",
        ),
        DeductionRule(
            code="IP-DISCHARGE-02",
            description="缺诊疗经过",
            deduct_points=1,
            checker=ic.discharge_missing_treatment_course,
            target_field="诊疗经过",
        ),
        DeductionRule(
            code="IP-DISCHARGE-03",
            description="缺出院诊断",
            deduct_points=1,
            checker=ic.discharge_missing_discharge_diagnosis,
            target_field="出院诊断",
        ),
        DeductionRule(
            code="IP-DISCHARGE-04",
            description="缺出院医嘱或注意事项无针对性",
            deduct_points=1,
            checker=ic.discharge_missing_discharge_advice,
            target_field="出院医嘱",
        ),
        DeductionRule(
            code="IP-DISCHARGE-05",
            description="缺出院情况",
            deduct_points=1,
            checker=ic.discharge_missing_discharge_status,
            target_field="出院情况",
        ),
    ),
)


# ─── 15. 知情同意书（10 分）— 暂不评分 ───────────────────────
_INFORMED_CONSENT = RubricItem(
    name="知情同意书",
    max_points=10,
    description="授权委托书/手术麻醉输血知情同意/病情沟通谈话（本系统暂不评分）",
    deduction_rules=(),  # TODO: 接入知情同意书数据后实装
)


# ─── 16. 会诊记录（4 分）— 暂不评分 ──────────────────────────
_CONSULTATION = RubricItem(
    name="会诊记录",
    max_points=4,
    description="普通会诊 24 小时内完成/会诊申请/会诊意见执行情况（本系统暂不评分）",
    deduction_rules=(),  # TODO: 接入会诊单数据后实装
)


# ─── 17. 医嘱单（2 分）— 暂不评分 ────────────────────────────
_ORDERS = RubricItem(
    name="医嘱单",
    max_points=2,
    description="医嘱内容清楚完整/开停时间/医师签名（本系统暂不评分）",
    deduction_rules=(),  # TODO: 接入医嘱单数据后实装
)


# ─── 18. 书写基本要求（4 分）— 暂不评分 ─────────────────────
_WRITING_REQUIREMENTS = RubricItem(
    name="书写基本要求",
    max_points=4,
    description="病历完整/非执业医师审签/修正规范/字迹清楚（本系统暂不评分）",
    deduction_rules=(),  # TODO: 接入审计层（签名/修改记录）后实装
)


# ─── 完整 Rubric 对象 ────────────────────────────────────────────────
ZJ_INPATIENT_V2021 = Rubric(
    name="浙江省中医住院病历评分标准",
    version="2021",
    # PDF 真意是"接诊整体综合评分"（多文档评分），标 encounter 表达此意图。
    # 当前实现简化为按单份病历评分（ctx 单文档），多文档综合评分待 ctx 架构扩展。
    # 选 encounter 还有一个副作用是允许 veto_rules——rubric.py 的 __post_init__
    # 约束 single scope 不能有 veto（业务规则：门诊无单项否决），住院 PDF 有大量 veto。
    record_scope="encounter",
    items=(
        _FRONT_PAGE,
        _ADMISSION_CHIEF_COMPLAINT,
        _ADMISSION_PRESENT_ILLNESS,
        _ADMISSION_PAST_HISTORY,
        _ADMISSION_SOCIAL_HISTORY,
        _ADMISSION_SPECIAL_ASSESSMENT,
        _ADMISSION_PHYSICAL_EXAM,
        _ADMISSION_AUXILIARY_EXAM,
        _ADMISSION_DIAGNOSIS,
        _FIRST_COURSE_RECORD,
        _SENIOR_ROUND,
        _COURSE_RECORD,
        _PERIOPERATIVE,
        _DISCHARGE_RECORD,
        _INFORMED_CONSENT,
        _CONSULTATION,
        _ORDERS,
        _WRITING_REQUIREMENTS,
    ),
    grade_thresholds=(
        # PDF 备注 8：90 分以下乙级，80 分以下丙级，90+ 甲级
        GradeThreshold(min_score=90, label="甲级"),
        GradeThreshold(min_score=80, label="乙级"),
        GradeThreshold(min_score=0, label="丙级"),
    ),
)

# 不变量自检：PDF 总分必须为 100（含占位的 5 大区）
assert ZJ_INPATIENT_V2021.total_points == 100, (
    f"住院评分表总分应为 100，当前为 {ZJ_INPATIENT_V2021.total_points}"
)
