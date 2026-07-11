"""住院评分规则 checker 函数库（_inpatient_checkers.py）

PDF 1:1 映射：浙江省住院病历质量检查评分表（2021 版）

为什么独立成文件：
  住院 rubric checker 数量多（30+ 个）+ 跨多个 record_type，
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

拆分说明（2026-07-11）：
  原单文件 318 行超过服务层 250 行硬约束，按病历类型拆成 4 个子模块：
    _inpatient_checkers_admission.py     入院记录（admission_note）
    _inpatient_checkers_first_course.py  首次病程录（first_course_record）
    _inpatient_checkers_discharge.py     出院记录（discharge_record）
    _inpatient_checkers_perioperative.py 围手术期（pre/op/post_op）
  本文件退化为聚合层：显式 re-export 全部函数，保证对外导入路径
  （app.services.qc_engine._inpatient_checkers.<函数名>）与函数名完全不变，
  rubrics/zj_inpatient_2021.py 中 `ic.xxx_checker` 的引用无需改动。
"""
from __future__ import annotations

# ─── 入院记录组（admission_note 触发） ──────────────────────────────
from app.services.qc_engine._inpatient_checkers_admission import (  # noqa: F401
    _is_admission_note,
    admission_chief_complaint_no_duration,
    admission_missing_allergy_history,
    admission_missing_auxiliary_exam,
    admission_missing_chief_complaint,
    admission_missing_current_medications,
    admission_missing_diagnosis,
    admission_missing_family_history,
    admission_missing_marital_or_menstrual_history,
    admission_missing_nutrition,
    admission_missing_pain_assessment,
    admission_missing_past_history,
    admission_missing_personal_history,
    admission_missing_physical_exam,
    admission_missing_present_illness,
    admission_missing_psychology,
    admission_missing_rehabilitation,
    admission_missing_religion,
    admission_missing_vte_risk,
    admission_present_illness_no_general_condition,
)

# ─── 首次病程录组（first_course_record 触发） ───────────────────────
from app.services.qc_engine._inpatient_checkers_first_course import (  # noqa: F401
    _is_first_course,
    first_course_missing_case_summary,
    first_course_missing_diagnosis_discussion,
    first_course_missing_treatment_plan,
)

# ─── 出院（死亡）记录组（discharge_record 触发） ────────────────────
from app.services.qc_engine._inpatient_checkers_discharge import (  # noqa: F401
    _is_discharge,
    discharge_missing_admission_status,
    discharge_missing_discharge_advice,
    discharge_missing_discharge_diagnosis,
    discharge_missing_discharge_status,
    discharge_missing_treatment_course,
)

# ─── 围手术期组（pre_op_summary / op_record / post_op_record 触发） ──
from app.services.qc_engine._inpatient_checkers_perioperative import (  # noqa: F401
    _is_perioperative,
    perioperative_op_record_missing_process,
    perioperative_post_op_missing_recovery,
    perioperative_pre_op_missing_indication,
    perioperative_pre_op_missing_plan,
)
