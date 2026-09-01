# -*- coding: utf-8 -*-
"""首次病程记录的标题不得带模板填空提示（2026-09-01 住院支线实测发现）。

原实现：
    title_line="首次病程记录\n（书写时间：入院后__小时内完成）"

那句是**空白模板上给医生看的书写要求**，不是病历内容；而且 __ 是硬编码字面量、
从来没有被任何代码替换过。结果每一份首次病程记录的正文第二行都印着
「（书写时间：入院后__小时内完成）」，医生签发后原样进法定文书——病案室归档、
医调委举证时看到的就是这句带空格线的模板提示。

时限提醒该待的地方是工作台的「文书时效」面板（那里已经在显示「剩余 8.0 小时」）。
"""
from app.services.ai._render_course import render_first_course_record

_DATA = {
    "case_summary": "患者女，63 岁，因上腹痛伴呕吐 2 天入院。",
    "preliminary_diagnosis": "急性胰腺炎",
    "tcm_syndrome_analysis": "腹痛（肝郁气滞证）",
    "diagnosis_discussion": "需与消化性溃疡穿孔、急性胆囊炎鉴别。",
    "treatment_plan": "禁食胃肠减压、抑酸抑酶、补液支持。",
}


def test_标题只有文书名():
    out = render_first_course_record(_DATA)
    assert out.split("\n")[0] == "首次病程记录"


def test_正文不含书写时限提示():
    """这是给医生看的模板要求，不该出现在法定文书上。"""
    out = render_first_course_record(_DATA)
    assert "书写时间" not in out
    assert "小时内完成" not in out


def test_正文不含未填充的下划线占位符():
    """__ 从来没有被替换过——它不是待填变量，是抄空白模板时留下的。"""
    out = render_first_course_record(_DATA)
    assert "__" not in out


def test_法定五章节仍齐全():
    """删标题提示不能碰内容结构：病例特点→初步诊断→中医辨证依据→拟诊讨论→诊疗计划。"""
    out = render_first_course_record(_DATA)
    for sec in ("【病例特点】", "【初步诊断】", "【中医辨证依据】",
                "【拟诊讨论】", "【诊疗计划】"):
        assert sec in out
