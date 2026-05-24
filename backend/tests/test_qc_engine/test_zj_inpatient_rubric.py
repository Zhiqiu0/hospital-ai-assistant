"""住院评分规则测试（test_zj_inpatient_rubric.py）

★ 治本核心防回归：浙江省住院 PDF 1:1 实现的契约测试。

测试组织：
  1. Rubric 结构不变量（总分 100 / items 18 / veto 数量 / 等级阈值）
  2. 每条 checker 的触发 + 不触发双样本（防 false positive / negative）
  3. 跨 record_type 守卫：admission_note 规则不应在 first_course_record 上触发
  4. 完整 record 端到端评分：合规样本 ≈ 满分；缺章节样本扣到对应等级
"""
from __future__ import annotations

import pytest

from app.services.qc_engine.checker import build_context
from app.services.qc_engine.rubrics.zj_inpatient_2021 import ZJ_INPATIENT_V2021
from app.services.qc_engine.scorer import score


# ─── 通用 build_context 默认参数 ──────────────────────────────────


def _ctx(record_text: str, **overrides):
    """构造测试用 ctx，常用字段提供默认值。"""
    defaults = {
        "patient_name": "张三",
        "patient_gender": "男",
        "patient_age": "45",
        "record_type": "admission_note",
        "is_first_visit": True,
    }
    defaults.update(overrides)
    return build_context(record_text, **defaults)


# ─── 1. Rubric 结构不变量 ────────────────────────────────────────


def test_inpatient_rubric_total_points_100():
    """PDF 总分 = 100（含 5 个占位 RubricItem）。"""
    assert ZJ_INPATIENT_V2021.total_points == 100


def test_inpatient_rubric_18_items():
    """18 个 RubricItem（PDF 8 评分区 + 5 占位 + 5 个入院记录子项）。"""
    # 实际 PDF 区块：病案首页 1 + 入院记录 8 子项 + 首次病程 1 + 上级查房 1 +
    # 日常病程 1 + 围手术期 1 + 出院 1 + 知情同意 1 + 会诊 1 + 医嘱 1 + 书写要求 1 = 18
    assert len(ZJ_INPATIENT_V2021.items) == 18


def test_inpatient_grade_thresholds():
    """住院 PDF 备注 8：≥90 甲级 / ≥80 乙级 / <80 丙级。"""
    thresholds = [(t.min_score, t.label) for t in ZJ_INPATIENT_V2021.grade_thresholds]
    assert thresholds == [(90, "甲级"), (80, "乙级"), (0, "丙级")]


def test_inpatient_record_scope_encounter():
    """PDF 真意是接诊整体评分——record_scope='encounter'。"""
    assert ZJ_INPATIENT_V2021.record_scope == "encounter"


def test_inpatient_has_veto_rules():
    """住院 PDF 大量"单项否决"——至少 2 条已实装（首次病程 + 围手术期）。"""
    total_veto = sum(len(it.veto_rules) for it in ZJ_INPATIENT_V2021.items)
    assert total_veto >= 2


def test_inpatient_placeholder_items_have_no_rules():
    """5 个占位 RubricItem（病案首页/知情同意/会诊/医嘱/书写要求）暂不评分——
    deduction_rules 必须为空 tuple，避免误扣分。"""
    placeholder_names = {"病案首页", "知情同意书", "会诊记录", "医嘱单", "书写基本要求"}
    for it in ZJ_INPATIENT_V2021.items:
        if it.name in placeholder_names:
            assert it.deduction_rules == (), f"{it.name} 是占位项不该有规则"


# ─── 2. 入院记录区规则（record_type='admission_note'） ───────────────


_FULL_ADMISSION = """【主诉】
反复胸痛 3 天

【现病史】
3 天前活动后突发胸骨后压榨样疼痛，持续 5-10 分钟，含服硝酸甘油可缓解。曾就诊于社区医院，行心电图检查未见明显异常。发病以来精神尚可，食欲一般，睡眠正常，二便正常。

【既往史】
高血压病史 10 年，最高 160/100mmHg，规律服用氨氯地平。否认糖尿病史。否认药物及食物过敏史。

【过敏史】
否认药物及食物过敏史

【个人史】
生于本地，久居本地，吸烟史 20 年，每日 1 包，否认饮酒史

【婚育史】
已婚，育有 1 子，配偶及子健康

【家族史】
父亲有冠心病史，母亲有高血压

【病史陈述者】
患者本人

【专项评估】
· 当前用药：氨氯地平 5mg qd
· 疼痛评估（NRS评分）：3 分
· 康复需求：暂无
· 心理状态：稳定
· 营养风险：低风险
· VTE风险：低危
· 宗教信仰/饮食禁忌：无

【体格检查】
T:36.5℃ P:78次/分 R:18次/分 BP:130/85mmHg
神清精神可，全身皮肤未见异常，心肺听诊未见异常

【辅助检查（入院前）】
心电图：窦性心律，未见 ST-T 异常

【入院诊断】
冠心病，不稳定型心绞痛"""


def test_admission_full_record_no_issues():
    """合规的入院记录——本系统能评分的入院区 8 子项不应触发任何扣分。"""
    ctx = _ctx(_FULL_ADMISSION, record_type="admission_note")
    report = score(ZJ_INPATIENT_V2021, ctx)
    # 入院记录 8 子项可扣分总和 = 2+6+2+3+3+2+2+4 = 24
    # 合规样本应扣 0 分（其他占位项也 0 分），总分 100
    admission_items = [
        it for it in report.item_scores
        if it.name.startswith("入院记录")
    ]
    total_admission_deducted = sum(it.deducted for it in admission_items)
    assert total_admission_deducted == 0, (
        f"合规入院记录不应扣分，但扣了 {total_admission_deducted}：\n"
        + "\n".join(f"  {it.name}: -{it.deducted}" for it in admission_items if it.deducted > 0)
    )


def test_admission_missing_chief_complaint_triggers():
    """缺主诉触发 IP-ADMISSION-CHIEF-01。"""
    text = _FULL_ADMISSION.replace("反复胸痛 3 天", "[未填写，需补充]")
    ctx = _ctx(text, record_type="admission_note")
    report = score(ZJ_INPATIENT_V2021, ctx)
    rule_codes = [d.rule_code for d in report.deductions]
    assert "IP-ADMISSION-CHIEF-01" in rule_codes


def test_admission_missing_allergy_history_triggers():
    """缺过敏史触发 IP-ADMISSION-PAST-02（扣 2 分）。

    构造场景：既往史和过敏史章节都不提"过敏"关键词，让 checker 触发。
    """
    text = _FULL_ADMISSION.replace(
        "高血压病史 10 年，最高 160/100mmHg，规律服用氨氯地平。否认糖尿病史。否认药物及食物过敏史。",
        "高血压病史 10 年，规律服用氨氯地平。",
    ).replace(
        "【过敏史】\n否认药物及食物过敏史",
        "【过敏史】\n[未填写，需补充]",
    )
    ctx = _ctx(text, record_type="admission_note")
    report = score(ZJ_INPATIENT_V2021, ctx)
    rule_codes = [d.rule_code for d in report.deductions]
    assert "IP-ADMISSION-PAST-02" in rule_codes, (
        f"应触发过敏史缺失规则，实际触发：{rule_codes}"
    )


def test_admission_missing_diagnosis_triggers():
    """缺入院诊断触发 IP-ADMISSION-DIAG-01（扣 2 分）。"""
    text = _FULL_ADMISSION.replace("冠心病，不稳定型心绞痛", "[未填写，需补充]")
    ctx = _ctx(text, record_type="admission_note")
    report = score(ZJ_INPATIENT_V2021, ctx)
    rule_codes = [d.rule_code for d in report.deductions]
    assert "IP-ADMISSION-DIAG-01" in rule_codes


def test_admission_missing_special_assessment_triggers():
    """专项评估某项缺触发对应独立规则（2026-05-24 拆 7 条治本后）。

    旧设计 1 条规则 IP-ADMISSION-ASSESS-01 打包 7 项 + target_field 错配
    引导去问诊面板。新设计 7 条独立规则：
      IP-ADMISSION-ASSESS-01 缺当前用药 / 02 缺疼痛评估 / 03 缺康复 /
      04 缺心理 / 05 缺营养 / 06 缺 VTE / 07 缺宗教信仰
    各自 target_field 指向具体子字段（当前用药 / 疼痛评估 ...）。
    """
    text = _FULL_ADMISSION.replace(
        "· 当前用药：氨氯地平 5mg qd",
        "· 当前用药：[未填写，需补充]",
    )
    ctx = _ctx(text, record_type="admission_note")
    report = score(ZJ_INPATIENT_V2021, ctx)
    rule_codes = [d.rule_code for d in report.deductions]
    assert "IP-ADMISSION-ASSESS-01" in rule_codes  # 缺当前用药
    # target_field 是具体可写字段，非 NON_WRITABLE 标记
    deduction = next(d for d in report.deductions if d.rule_code == "IP-ADMISSION-ASSESS-01")
    assert deduction.target_field == "当前用药"


# ─── 3. 首次病程录规则（含 veto） ────────────────────────────────


_FULL_FIRST_COURSE = """首次病程记录
（书写时间：入院后__小时内完成）

【病例特点】
1. 中年男性，急性起病。
2. 主要症状：活动后胸骨后压榨样疼痛，持续 5-10 分钟，含服硝酸甘油可缓解。
3. 高血压病史 10 年，吸烟史 20 年，父亲有冠心病史，存在多个心血管危险因素。
4. 体征：BP 130/85mmHg，心肺听诊未见明显异常。
5. 辅助检查：心电图未见明显异常。

【拟诊讨论】
初步诊断：冠心病，不稳定型心绞痛。诊断依据：典型胸痛症状 + 多重危险因素。鉴别诊断：1) 胃食管反流 2) 主动脉夹层。需进一步行冠脉造影明确。

【诊疗计划】
1. 完善冠脉 CTA 或冠脉造影
2. 阿司匹林、阿托伐他汀治疗
3. 监测心电图及心肌酶
4. 病情观察"""


def test_first_course_full_no_issues():
    """合规首次病程——首次病程项不应扣分。"""
    ctx = _ctx(_FULL_FIRST_COURSE, record_type="first_course_record")
    report = score(ZJ_INPATIENT_V2021, ctx)
    fc_items = [it for it in report.item_scores if it.name == "首次病程录"]
    assert fc_items[0].deducted == 0


def test_first_course_missing_case_summary_triggers_veto():
    """缺病例特点触发单项否决 IP-FIRST-COURSE-VETO-01（扣 10 分不累积）。"""
    text = _FULL_FIRST_COURSE.replace(
        "【病例特点】\n1. 中年男性，急性起病。",
        "【病例特点】\n[未填写，需补充]",
    ).split("2. 主要症状")[0]
    text += "\n\n【拟诊讨论】\n初步诊断：冠心病\n\n【诊疗计划】\n完善检查"
    ctx = _ctx(text, record_type="first_course_record")
    report = score(ZJ_INPATIENT_V2021, ctx)
    fc_items = [it for it in report.item_scores if it.name == "首次病程录"]
    assert fc_items[0].veto_triggered is True
    assert fc_items[0].deducted == 6  # VETO 扣 10 但 cap 到 max_points=6


def test_first_course_missing_treatment_plan_triggers():
    """缺诊疗计划触发 IP-FIRST-COURSE-02。"""
    text = _FULL_FIRST_COURSE.replace(
        "【诊疗计划】\n1. 完善冠脉 CTA 或冠脉造影",
        "【诊疗计划】\n[未填写，需补充]",
    ).split("2. 阿司匹林")[0]
    ctx = _ctx(text, record_type="first_course_record")
    report = score(ZJ_INPATIENT_V2021, ctx)
    rule_codes = [d.rule_code for d in report.deductions]
    assert "IP-FIRST-COURSE-02" in rule_codes


# ─── 4. 出院记录规则 ───────────────────────────────────────────────


_FULL_DISCHARGE = """出院记录

【主诉】
反复胸痛 3 天

【入院情况】
入院时神志清楚，BP 130/85mmHg，心率 78 次/分，心肺听诊未见异常。心电图未见明显 ST-T 改变。

【入院诊断】
冠心病，不稳定型心绞痛

【诊疗经过】
入院后完善冠脉 CTA 提示前降支中段 70% 狭窄。予阿司匹林、阿托伐他汀、单硝酸异山梨酯口服，症状缓解。经患方知情同意，行 PCI 术，于前降支植入支架 1 枚。术后恢复良好。

【出院情况】
神清，胸痛症状缓解，BP 125/80mmHg，心率 70 次/分。

【出院诊断】
冠心病，不稳定型心绞痛（PCI 术后）

【出院医嘱】
1. 阿司匹林肠溶片 100mg qd 长期
2. 替格瑞洛 90mg bid 至少 12 个月
3. 阿托伐他汀 20mg qn 长期
4. 1 周后心内科门诊复诊
5. 如再发胸痛立即就诊"""


def test_discharge_full_no_issues():
    """合规出院记录——出院项不扣分。"""
    ctx = _ctx(_FULL_DISCHARGE, record_type="discharge_record")
    report = score(ZJ_INPATIENT_V2021, ctx)
    dc_items = [it for it in report.item_scores if it.name == "出院（死亡）记录"]
    assert dc_items[0].deducted == 0


def test_discharge_missing_treatment_course_triggers():
    """缺诊疗经过触发 IP-DISCHARGE-02。"""
    text = _FULL_DISCHARGE.replace(
        "入院后完善冠脉 CTA 提示前降支中段 70% 狭窄。",
        "[未填写，需补充]",
    ).split("予阿司匹林")[0] + "\n\n【出院情况】"
    text = _FULL_DISCHARGE.replace(
        "入院后完善冠脉 CTA 提示前降支中段 70% 狭窄。予阿司匹林、阿托伐他汀、单硝酸异山梨酯口服，症状缓解。经患方知情同意，行 PCI 术，于前降支植入支架 1 枚。术后恢复良好。",
        "[未填写，需补充]",
    )
    ctx = _ctx(text, record_type="discharge_record")
    report = score(ZJ_INPATIENT_V2021, ctx)
    rule_codes = [d.rule_code for d in report.deductions]
    assert "IP-DISCHARGE-02" in rule_codes


# ─── 5. 跨 record_type 守卫（治本核心） ─────────────────────────────


def test_admission_rules_not_triggered_on_first_course():
    """治本核心：入院记录规则不应在 first_course_record 上触发——
    避免医生在首次病程录跑质控时被"缺主诉/缺现病史"等入院记录字段误报。
    """
    # 首次病程录正文：完整，但不含入院记录的章节（主诉/现病史/既往史等）
    ctx = _ctx(_FULL_FIRST_COURSE, record_type="first_course_record")
    report = score(ZJ_INPATIENT_V2021, ctx)
    # 任何 IP-ADMISSION-* 都不应触发
    admission_codes = [d.rule_code for d in report.deductions if d.rule_code.startswith("IP-ADMISSION-")]
    assert admission_codes == [], (
        f"入院记录规则在 first_course_record 上误触发：{admission_codes}"
    )


def test_discharge_rules_not_triggered_on_admission():
    """治本核心：出院记录规则不应在 admission_note 上触发。"""
    ctx = _ctx(_FULL_ADMISSION, record_type="admission_note")
    report = score(ZJ_INPATIENT_V2021, ctx)
    discharge_codes = [d.rule_code for d in report.deductions if d.rule_code.startswith("IP-DISCHARGE-")]
    assert discharge_codes == [], (
        f"出院规则在 admission_note 上误触发：{discharge_codes}"
    )


def test_outpatient_emergency_rules_not_in_inpatient_rubric():
    """治本核心：门急诊 rule_code 不应出现在住院 rubric 评分结果里。"""
    ctx = _ctx(_FULL_ADMISSION, record_type="admission_note")
    report = score(ZJ_INPATIENT_V2021, ctx)
    op_codes = [d.rule_code for d in report.deductions if d.rule_code.startswith("OP-")]
    assert op_codes == [], (
        f"门急诊规则（OP-* 前缀）出现在住院评分结果：{op_codes}"
    )


def test_visit_time_not_required_in_inpatient():
    """治本验证：住院病历不要求"就诊时间："行——不应有任何"无就诊时间"扣分。

    历史 bug：用户在住院首次病程上跑质控时，OP-BASIC-INFO-02 触发"无就诊时间"
    + UI 引导"请在病历最上方就诊时间那一行修改"——但住院模板没渲染那一行。
    """
    # 首次病程录正文没有"就诊时间："行
    ctx = _ctx(_FULL_FIRST_COURSE, record_type="first_course_record")
    report = score(ZJ_INPATIENT_V2021, ctx)
    for d in report.deductions:
        assert "就诊时间" not in d.description, (
            f'住院评分不该有就诊时间相关扣分：{d}'
        )


# ─── 6. _select_rubric 路由测试 ────────────────────────────────────


def test_select_rubric_routes_inpatient_to_inpatient_rubric():
    """_select_rubric 必须把 8 种住院 record_type 路由到 ZJ_INPATIENT_V2021。"""
    from app.services.ai.qc_stream_service import _select_rubric, _INPATIENT_RECORD_TYPES

    for rt in _INPATIENT_RECORD_TYPES:
        rubric = _select_rubric(rt)
        assert rubric is ZJ_INPATIENT_V2021, (
            f"{rt} 应路由到住院 rubric，实际：{rubric.name}"
        )


def test_select_rubric_routes_outpatient_to_outpatient_rubric():
    """门急诊路由不变。"""
    from app.services.ai.qc_stream_service import _select_rubric
    from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
        ZJ_OUTPATIENT_EMERGENCY_V2023,
    )

    for rt in ("outpatient", "emergency"):
        assert _select_rubric(rt) is ZJ_OUTPATIENT_EMERGENCY_V2023


# ─── 7. 端到端评分（等级判定） ────────────────────────────────────


def test_full_admission_record_gets_jia_grade():
    """合规入院记录应得甲级（≥90）。"""
    ctx = _ctx(_FULL_ADMISSION, record_type="admission_note")
    report = score(ZJ_INPATIENT_V2021, ctx)
    assert report.score >= 90, f"合规病历应≥90，实际 {report.score}"
    assert report.grade == "甲级"
    assert report.passed is True


def test_first_course_with_veto_drops_grade():
    """首次病程缺病例特点触发 veto → 扣 6 分（首次病程满分 6） → 100-6=94 → 仍甲级
    但 veto_triggered=True 可在 UI 上单独标识。"""
    text = """首次病程记录

【病例特点】
[未填写，需补充]

【拟诊讨论】
初步诊断：肺炎

【诊疗计划】
完善胸部 CT"""
    ctx = _ctx(text, record_type="first_course_record")
    report = score(ZJ_INPATIENT_V2021, ctx)
    fc_items = [it for it in report.item_scores if it.name == "首次病程录"]
    assert fc_items[0].veto_triggered is True
