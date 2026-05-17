"""门急诊评分规则双样本测试（test_zj_outpatient_rubric.py）

★ 治本核心防回归：每条门急诊规则都用"触发样本 + 不触发样本"两个 fixture
验证。这是浙江省评分标准的强契约——加新规则必须同时加两个样本，CI 强制。

关键防线：
  - 触发场景：占位符 / 空章节 / 缺失字段 → 规则必触发扣分
  - 不触发场景：医生填了合规内容 → 规则必不触发
"""
import pytest

from app.services.qc_engine.checker import build_context
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023,
)
from app.services.qc_engine.scorer import score


# ─── 病历样本构造 ───────────────────────────────────────────────────


def _build_full_record() -> str:
    """构造一份"完美"门诊病历——任何门诊规则都不应触发扣分。"""
    return """就诊时间：2026-05-18 10:30　病发时间：2026-05-15 08:00

【主诉】
反复头痛 3 天

【现病史】
患者 3 天前无明显诱因出现头部胀痛，伴轻度恶心，无呕吐发热。曾自行服用对乙酰氨基酚片治疗，效果不佳。今为求中医诊治来院就诊。发病以来精神尚可，食欲一般，睡眠欠佳，二便正常。

【既往史】
否认高血压、糖尿病等慢性病史。否认手术外伤史。否认药物及食物过敏史。

【过敏史】
否认药物及食物过敏史

【个人史】
生于本地，久居本地，否认吸烟饮酒史，否认疫区接触史

【体格检查】
T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg
望诊：神清，面色正常
闻诊：语声清晰
切诊·舌象：舌淡红，苔薄白
切诊·脉象：脉弦
其余阳性体征：心肺听诊未见异常

【辅助检查】
血常规未见异常，头颅 CT 未见占位

【诊断】
中医疾病诊断：头痛
中医证候诊断：风寒头痛证
西医诊断：紧张型头痛

【治疗意见及措施】
治则治法：疏风散寒，止痛
处理意见：川芎茶调散加减
复诊建议：1 周后复诊
注意事项：避风寒，规律作息"""


def _full_inquiry() -> dict:
    return {
        "patient_name": "测试王某",
        "patient_gender": "男",
        "patient_age": "45",
    }


def _build_record_missing(section_name: str) -> str:
    """从满分病历里去掉某章节（用占位符替换）—— 验证规则在该场景下触发。"""
    full = _build_full_record()
    # 简单做法：把章节标题之后到下一个空行的内容替换为占位符
    import re
    pattern = rf"(【{section_name}】\n)(.+?)(\n\n|\Z)"
    return re.sub(pattern, r"\1[未填写，需补充]\3", full, count=1, flags=re.DOTALL)


# ─── 满分病历不触发任何扣分 ──────────────────────────────────────


def test_full_record_yields_perfect_score():
    """治本核心：完整合规病历评分 = 满分 + 合格。

    这是"治本"对立面的验证：满分病历也必须 100 分（不能误扣）。
    """
    ctx = build_context(
        _build_full_record(),
        record_type="outpatient",
        is_first_visit=True,
        patient_gender="男",
        inquiry=_full_inquiry(),
    )
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    assert rep.passed is True
    assert rep.grade == "合格"
    # 仅"知情同意书"这一项还没接入数据，规则空 tuple，扣 0 分——满分 100
    assert rep.score == 100, f"满分病历应得 100 分，实际 {rep.score}，扣分明细：{[(d.rule_code, d.points) for d in rep.deductions]}"


# ─── 用户截图复现：5 个未填写章节绝不能再 100 分 ──────────────────


def test_user_screenshot_scenario_does_not_yield_100():
    """★ 用户截图原始 bug 场景：5 个占位符章节绝不能再显示 100 分。

    这是治本最核心的断言——旧实现这个场景是 100 分甲级，
    新实现必须扣足够多的分使其不合格。
    """
    record = """就诊时间：2026-05-18 10:30

【主诉】
咽痛如含刀片，伴咳嗽、腹泻、全身无力

【现病史】
患者于近期出现腹泻，呈水样便，后出现咽痛如含刀片，伴咳嗽、全身无力。

【既往史】
[未填写，需补充]

【过敏史】
[未填写，需补充]

【个人史】
[未填写，需补充]

【体格检查】
[未填写，需补充]
望诊：[未填写，需补充]
闻诊：[未填写，需补充]
切诊·舌象：[未填写，需补充]
切诊·脉象：[未填写，需补充]
其余阳性体征：[未填写，需补充]

【辅助检查】
感染指标（CRP/PCT/ESR）、便常规

【诊断】
急性咽炎

【治疗意见及措施】
治则治法：[未填写，需补充]
处理意见：[未填写，需补充]
复诊建议：[未填写，需补充]
注意事项：[未填写，需补充]"""

    ctx = build_context(
        record,
        record_type="outpatient",
        is_first_visit=True,
        patient_gender="男",
        inquiry={"patient_name": "测试", "patient_gender": "男", "patient_age": "35"},
    )
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    # 必触发：缺中医四诊（-10）、缺治则治法（-5）、缺处理意见（-5）、缺复诊建议+注意事项（-5）、
    #         缺中医疾病诊断（-10）、缺西医诊断（-2，因为只有"急性咽炎"未明确归类为西医诊断章节）
    assert rep.score < 90, f"用户截图场景应不合格（<90），实际 {rep.score} —— bug 复发"
    assert rep.grade == "不合格", f"用户截图场景必须显示'不合格'，实际 {rep.grade}"
    # 触发的规则应包含中医四诊缺失
    triggered_codes = {d.rule_code for d in rep.deductions}
    assert "OP-PHYSICAL-EXAM-01" in triggered_codes, "中医四诊缺失规则必须触发"


# ─── 每条规则的双样本（触发 + 不触发） ──────────────────────────


# 主诉 ──────────────────────────────────────────────────────────


def test_chief_complaint_missing_triggers_deduction():
    """主诉缺失 → OP-CHIEF-COMPLAINT-01 触发。"""
    ctx = build_context(_build_record_missing("主诉"), inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-CHIEF-COMPLAINT-01" in codes


def test_chief_complaint_without_duration_triggers_deduction():
    """主诉缺时间单位（天/周/月/年/小时）→ OP-CHIEF-COMPLAINT-02 触发。"""
    record = _build_full_record().replace("反复头痛 3 天", "反复头痛")
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-CHIEF-COMPLAINT-02" in codes


# 现病史 ────────────────────────────────────────────────────────


def test_present_illness_missing_triggers_deduction():
    ctx = build_context(_build_record_missing("现病史"), inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-PRESENT-ILLNESS-01" in codes


def test_present_illness_without_treatment_keyword_triggers_deduction():
    """现病史缺诊治经过描述（无"治疗/服药/就诊/检查/用药"等关键词）→ -02 触发。"""
    record = _build_full_record().replace(
        "患者 3 天前无明显诱因出现头部胀痛，伴轻度恶心，无呕吐发热。曾自行服用对乙酰氨基酚片治疗，效果不佳。今为求中医诊治来院就诊。发病以来精神尚可，食欲一般，睡眠欠佳，二便正常。",
        "患者 3 天前出现头痛，无其他症状。"
    )
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-PRESENT-ILLNESS-02" in codes


# 既往史 ────────────────────────────────────────────────────────


def test_past_history_missing_triggers_deduction():
    ctx = build_context(_build_record_missing("既往史"), inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-PAST-HISTORY-01" in codes


def test_female_in_reproductive_age_missing_menstrual_history_triggers():
    """育龄女性无月经史 → OP-PAST-HISTORY-02 触发（-5 分）。"""
    record = _build_full_record()  # 既往史含"否认...过敏史"但不含"经"字
    ctx = build_context(
        record,
        patient_gender="女",
        inquiry={"patient_name": "测试", "patient_gender": "女", "patient_age": "30"},
    )
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-PAST-HISTORY-02" in codes


def test_male_does_not_trigger_menstrual_history_rule():
    """男性不触发月经史规则。"""
    ctx = build_context(
        _build_full_record(),
        patient_gender="男",
        inquiry=_full_inquiry(),
    )
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-PAST-HISTORY-02" not in codes


# 体格检查 ──────────────────────────────────────────────────────


def test_missing_tongue_and_pulse_triggers_tcm_four_diagnoses():
    """舌象 + 脉象都缺 → OP-PHYSICAL-EXAM-01 触发（-10 分）。"""
    record = _build_full_record() \
        .replace("切诊·舌象：舌淡红，苔薄白", "切诊·舌象：[未填写，需补充]") \
        .replace("切诊·脉象：脉弦", "切诊·脉象：[未填写，需补充]")
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-PHYSICAL-EXAM-01" in codes


def test_filled_tcm_diagnoses_does_not_trigger():
    """舌脉填了 → 不触发。"""
    ctx = build_context(_build_full_record(), inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-PHYSICAL-EXAM-01" not in codes


# 辅助检查 ──────────────────────────────────────────────────────


def test_missing_auxiliary_exam_triggers_deduction():
    ctx = build_context(_build_record_missing("辅助检查"), inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-AUXILIARY-EXAM-01" in codes


# 诊断 ─────────────────────────────────────────────────────────


def test_missing_tcm_diagnosis_triggers_deduction():
    """中医疾病诊断缺失 → OP-DIAGNOSIS-01 触发（-10 分）。"""
    record = _build_full_record().replace(
        "中医疾病诊断：头痛\n中医证候诊断：风寒头痛证\n西医诊断：紧张型头痛",
        "西医诊断：紧张型头痛"
    )
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-DIAGNOSIS-01" in codes


def test_incomplete_tcm_diagnosis_triggers_deduction():
    """有疾病诊断但无证候诊断 → OP-DIAGNOSIS-02 触发（-2 分）。"""
    record = _build_full_record().replace(
        "中医证候诊断：风寒头痛证\n",
        ""
    )
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-DIAGNOSIS-02" in codes


def test_missing_western_diagnosis_triggers_deduction():
    record = _build_full_record().replace(
        "西医诊断：紧张型头痛", ""
    )
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-DIAGNOSIS-03" in codes


# 治疗意见 ─────────────────────────────────────────────────────


def test_missing_treatment_plan_triggers_deduction():
    record = _build_full_record().replace(
        "处理意见：川芎茶调散加减", "处理意见：[未填写，需补充]"
    )
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-TREATMENT-01" in codes


def test_missing_treatment_method_triggers_deduction():
    record = _build_full_record().replace(
        "治则治法：疏风散寒，止痛", "治则治法：[未填写，需补充]"
    )
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-TREATMENT-02" in codes


def test_missing_both_followup_and_precautions_triggers_deduction():
    """复诊建议 + 注意事项都缺 → -03 触发。"""
    record = _build_full_record().replace(
        "复诊建议：1 周后复诊\n注意事项：避风寒，规律作息",
        "复诊建议：[未填写，需补充]\n注意事项：[未填写，需补充]"
    )
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-TREATMENT-03" in codes


def test_one_of_followup_or_precautions_does_not_trigger():
    """复诊建议有 / 注意事项无 → 不触发（PDF 是 OR 关系，任一有即合规）。"""
    record = _build_full_record().replace(
        "注意事项：避风寒，规律作息", "注意事项：[未填写，需补充]"
    )
    ctx = build_context(record, inquiry=_full_inquiry())
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-TREATMENT-03" not in codes


# 急诊补充规则 ─────────────────────────────────────────────────


def test_emergency_visit_time_without_minute_triggers_deduction():
    """急诊就诊时间未到分钟（如"2026-05-18"无 HH:MM）→ OP-OTHER-01 触发。"""
    record = _build_full_record().replace("2026-05-18 10:30", "2026-05-18")
    ctx = build_context(
        record,
        record_type="emergency",
        is_emergency=True,
        inquiry=_full_inquiry(),
    )
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-OTHER-01" in codes


def test_outpatient_visit_time_without_minute_does_not_trigger():
    """门诊就诊时间不要求到分钟 → 不触发。"""
    record = _build_full_record().replace("2026-05-18 10:30", "2026-05-18")
    ctx = build_context(
        record,
        record_type="outpatient",
        is_emergency=False,
        inquiry=_full_inquiry(),
    )
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, ctx)
    codes = {d.rule_code for d in rep.deductions}
    assert "OP-OTHER-01" not in codes
