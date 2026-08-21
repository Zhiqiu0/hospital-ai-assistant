# -*- coding: utf-8 -*-
"""病案首页 10 分规则行为测试（2026-08-21 阶段3）。

每条规则触发/不触发双样本；核心不变量：front_page 未预取（loaded=False）时
一切首页规则不触发——兼容全部纯文本调用方与既有测试。
"""
from app.services.qc_engine.checker import FrontPageData, build_context
from app.services.qc_engine.rubrics.zj_inpatient_2021 import ZJ_INPATIENT_V2021
from app.services.qc_engine.scorer import score

_TEXT = "【主诉】\n发热 3 天\n\n【入院诊断】\n肺炎"

# 张三：合法 18 位身份证（校验位正确，男，1970-01-01）
_VALID_ID = "110101197001011959"


def _fp(**kw) -> FrontPageData:
    base = dict(
        id_card=_VALID_ID, birth_date="1970-01-01", gender="male",
        blood_type="A", admission_route="门诊", allergy_history="否认药物过敏",
        diagnoses=(
            {"category": "western", "name": "肺炎", "code": "J18.900",
             "is_primary": True, "admission_condition": "有"},
        ),
        loaded=True,
    )
    base.update(kw)
    return FrontPageData(**base)


def _codes(front_page: FrontPageData | None, record_type: str = "admission_note") -> set[str]:
    ctx = build_context(
        _TEXT, record_type=record_type, patient_name="张三",
        patient_gender="男", patient_age="56", front_page=front_page,
    )
    report = score(ZJ_INPATIENT_V2021, ctx)
    return {d.rule_code for d in report.deductions if d.rule_code.startswith("IP-FP")}


def test_not_loaded_triggers_nothing():
    """未预取（默认空 front_page）→ 首页规则全不触发（兼容纯文本调用方）。"""
    assert _codes(None) == set()


def test_complete_front_page_no_deductions():
    assert _codes(_fp()) == set()


def test_invalid_id_card_checksum_vetoes():
    assert "IP-FP-VETO-01" in _codes(_fp(id_card="110101197001011951"))


def test_id_card_gender_conflict_vetoes():
    """身份证性别位（第17位奇=男）与档案性别矛盾 → veto。"""
    assert "IP-FP-VETO-01" in _codes(_fp(gender="female"))


def test_id_card_birth_conflict_vetoes():
    assert "IP-FP-VETO-01" in _codes(_fp(birth_date="1980-05-05"))


def test_missing_id_card_is_not_an_error():
    """未录身份证 ≠ 信息错误（漏填不走 veto 口径）。"""
    assert "IP-FP-VETO-01" not in _codes(_fp(id_card=""))


def test_no_primary_diagnosis_vetoes():
    dx = ({"category": "western", "name": "肺炎", "is_primary": False,
           "admission_condition": "有"},)
    assert "IP-FP-VETO-02" in _codes(_fp(diagnoses=dx))
    # 条目整体为空也算主诊断缺失
    assert "IP-FP-VETO-02" in _codes(_fp(diagnoses=()))


def test_missing_admission_condition_deducts():
    dx = ({"category": "western", "name": "肺炎", "is_primary": True,
           "admission_condition": None},)
    assert "IP-FP-01" in _codes(_fp(diagnoses=dx))
    # 证候条目不要求入院病情标志
    dx2 = (
        {"category": "western", "name": "肺炎", "is_primary": True, "admission_condition": "有"},
        {"category": "tcm_syndrome", "name": "痰热壅肺证", "is_primary": False,
         "admission_condition": None},
    )
    assert "IP-FP-01" not in _codes(_fp(diagnoses=dx2))


def test_missing_route_allergy_blood_deduct():
    assert "IP-FP-02" in _codes(_fp(admission_route=""))
    assert "IP-FP-03" in _codes(_fp(allergy_history=""))
    assert "IP-FP-04" in _codes(_fp(blood_type=""))


def test_frontpage_rules_skip_course_records():
    """首页规则只在入院记录/出院记录上触发——日常病程不触发。

    注意 broken 样本保留合法诊断条目：若诊断为空会先触发 VETO-02，
    而 PDF 备注 6 规定 veto 后同大项不再累积扣分（scorer 已实现该语义），
    IP-FP-02 就看不到了。"""
    broken = _fp(admission_route="", blood_type="")
    assert _codes(broken, record_type="course_record") == set()
    assert "IP-FP-02" in _codes(broken, record_type="discharge_record")


def test_veto_suppresses_item_deductions():
    """PDF 备注 6：单项否决后同大项不再累积——诊断空(veto)时漏填细则不再报。"""
    broken = _fp(admission_route="", blood_type="", diagnoses=())
    codes = _codes(broken)
    assert "IP-FP-VETO-02" in codes
    assert "IP-FP-02" not in codes and "IP-FP-04" not in codes
