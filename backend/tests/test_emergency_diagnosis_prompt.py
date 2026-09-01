# -*- coding: utf-8 -*-
"""急诊病历的诊断必须进 prompt（2026-09-01 急诊支线端到端实测发现）。

原实现：
    f"诊断：{coalesce_field(getattr(req, 'initial_impression', None))}"
取的是「初步印象（补充）」这个**可选**框，医生真正填的西医诊断、中医疾病/证候
诊断一个都没进 prompt。结果 LLM 看到的诊断永远是空，急诊病历正文的【诊断】
章节恒为「[未填写，需补充]」。

实测复现：填西医「急性下壁心肌梗死」(I21.103) + 中医「胸痹」，diagnoses 表两条
都正确落库、HIS 回写的 diagnoses[] 也有值，**唯独病历正文诊断栏是空的**——
结构化数据与法定文书正文不一致。而急诊恰恰是最需要明确诊断的场景。
"""
import pytest

from app.services.ai.record_prompts import build_emergency_prompt


class _Req:
    """急诊生成请求的最小替身，只带 prompt 会读的字段。"""

    def __init__(self, **kw):
        defaults = dict(
            chief_complaint="突发胸痛1小时",
            history_present_illness="静息时突发胸骨后压榨性疼痛，伴大汗。",
            past_history="", allergy_history="",
            physical_exam="", physical_exam_vitals="", auxiliary_exam="",
            western_diagnosis=None, tcm_disease_diagnosis=None,
            tcm_syndrome_diagnosis=None, initial_impression=None,
            treatment_plan="吸氧、心电监护", observation_notes="",
            patient_disposition="收入住院",
            patient_name="张三", patient_gender="男", patient_age="54岁",
        )
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


def test_西医诊断必须进prompt():
    p = build_emergency_prompt(_Req(western_diagnosis="急性下壁心肌梗死"))
    assert "急性下壁心肌梗死" in p, "医生填的西医诊断没进 prompt——正文诊断栏会是空的"


def test_中医诊断也要进prompt():
    p = build_emergency_prompt(_Req(tcm_disease_diagnosis="胸痹",
                                    tcm_syndrome_diagnosis="气滞血瘀证"))
    assert "胸痹" in p
    assert "气滞血瘀证" in p


def test_西医与中医诊断并存时都在():
    """急诊【诊断】是扁平一行、不分中西医，但两者都得在。"""
    p = build_emergency_prompt(_Req(western_diagnosis="急性下壁心肌梗死",
                                    tcm_disease_diagnosis="胸痹"))
    assert "急性下壁心肌梗死" in p and "胸痹" in p


def test_初步印象仍作为补充保留():
    """它本来就是「暂时无法明确时的印象或鉴别方向」，不该丢，只是不能当主诊断源。"""
    p = build_emergency_prompt(_Req(initial_impression="待排主动脉夹层"))
    assert "待排主动脉夹层" in p


def test_诊断全空时给占位符而不是空串():
    """空诊断要让 LLM 看到明确的占位符，而不是一个空行——后者会被当成"无要求"。"""
    from app.services.ai.record_schemas import PLACEHOLDER
    p = build_emergency_prompt(_Req())
    assert f"诊断：{PLACEHOLDER}" in p


@pytest.mark.parametrize("field,value", [
    ("western_diagnosis", "急性下壁心肌梗死"),
    ("tcm_disease_diagnosis", "胸痹"),
])
def test_单独填任一诊断都不会丢(field, value):
    p = build_emergency_prompt(_Req(**{field: value}))
    assert value in p
