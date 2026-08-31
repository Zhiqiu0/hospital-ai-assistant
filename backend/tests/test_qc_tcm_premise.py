# -*- coding: utf-8 -*-
"""中医专项扣分必须以「有中医治疗」为前提（2026-08-31 中医语义审计回归锁）。

《浙江省中医门、急诊病历评分标准》原文（已逐字核对 docs/ 下的 PDF）：
  · 诊断项    ——「**有中医治疗的病历**无中医诊断扣 10 分，中医诊断不全扣 2 分」
  · 治疗意见项——「**实施中医治疗的**应当遵循辨证论治的原则」→ 治则治法扣 5 分

系统此前只实现了急诊豁免，把 PDF 白纸黑字的前提整个丢了。落地医院是**中西医
结合**医院，纯西医门诊（外科清创、皮肤科、五官科）是日常，被平白扣掉 15 分后
一份写得完整的清创病历判「不合格」，签发按钮置灰——医生要么编一个中医病名和
证型（病历造假），要么学会「别点质控直接签」（质控体系形同虚设）。

注：体格检查项「缺中医四诊扣 10 分」在 PDF 里**确实无前提**，故本次不动，
    那 10 分仍会扣在纯西医病历上（待医院医务科明确口径）。
"""
from app.services.qc_engine.checker import build_context
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023 as RUBRIC,
)
from app.services.qc_engine.scorer import score

# 纯西医外科清创门诊病历：通篇没有任何中医要素
PURE_WESTERN = """【主诉】右手食指割伤 2 小时
【现病史】患者 2 小时前家中切菜时被菜刀割伤右手食指，当即出血，自行按压止血后来诊。
未行特殊处理，无头晕、恶心。
【既往史】否认高血压、糖尿病史
【过敏史】否认药物、食物过敏史
【体格检查】右手食指近节掌侧见一长约 1.5cm 斜行裂口，深达皮下，创缘整齐，指端血运良好。
【辅助检查】血常规未见异常
【西医诊断】右手食指皮肤裂伤
【处理意见】1. 清创缝合术；2. 破伤风抗毒素 1500U 肌注；3. 头孢呋辛酯片 0.25g bid po
【复诊建议】2 日后换药，如出现红肿热痛及时就诊
"""

META = {"patient_name": "张三", "patient_gender": "男", "patient_age": "45岁"}


def _deduction_codes(text: str) -> set[str]:
    rep = score(RUBRIC, build_context(text, record_type="outpatient", **META))
    return {d.rule_code for it in rep.item_scores for d in it.deductions}


def test_纯西医门诊不扣中医诊断与治则治法():
    codes = _deduction_codes(PURE_WESTERN)
    assert "OP-DIAGNOSIS-01" not in codes, "纯西医病历被扣了「无中医诊断」10 分"
    assert "OP-DIAGNOSIS-02" not in codes, "纯西医病历被扣了「中医诊断不全」2 分"
    assert "OP-TREATMENT-02" not in codes, "纯西医病历被扣了「治则治法缺失」5 分"


def test_写了中医病名就要按中医病历全套判():
    """医生一旦开始写中医内容，缺证候/缺治则治法就该扣——不能因为这次放宽
    而让真正的中医病历也躲掉扣分。"""
    text = PURE_WESTERN.replace("【西医诊断】右手食指皮肤裂伤",
                                "【中医疾病诊断】金疮")
    codes = _deduction_codes(text)
    assert "OP-DIAGNOSIS-02" in codes, "写了中医病名却没写证候，应扣中医诊断不全"
    assert "OP-TREATMENT-02" in codes, "写了中医病名却没写治则治法，应扣 5 分"


def test_开了中药也算实施中医治疗():
    """诊断栏一个中医字都没有，但处理意见里开了中药——同样是中医诊疗。"""
    text = PURE_WESTERN.replace(
        "3. 头孢呋辛酯片 0.25g bid po",
        "3. 中药汤剂：桃红四物汤加减 7 剂，水煎服，日一剂")
    codes = _deduction_codes(text)
    assert "OP-DIAGNOSIS-01" in codes, "开了中药却无中医诊断，应扣 10 分"


def test_针灸推拿等中医疗法同样触发():
    text = PURE_WESTERN.replace("1. 清创缝合术；", "1. 针灸治疗，取足三里、合谷；")
    assert "OP-DIAGNOSIS-01" in _deduction_codes(text)


def test_西药剂型字眼不得误判成中医病历():
    """「颗粒」「散」「丸」是中西药通用剂型，不能凭它们把西医病历判成中医病历
    ——那等于把这次修掉的 15 分又扣回去。"""
    text = PURE_WESTERN.replace(
        "3. 头孢呋辛酯片 0.25g bid po",
        "3. 蒙脱石散 3g tid po；4. 布洛芬缓释胶囊 0.3g bid po")
    codes = _deduction_codes(text)
    assert "OP-DIAGNOSIS-01" not in codes
    assert "OP-TREATMENT-02" not in codes
