"""
病程 / 手术类病历渲染器（services/ai/_render_course.py）

record_renderer.py 拆分出的「病程类」渲染器（薄壳，复用 _render_common
里的两个通用渲染器）：首次病程 / 日常病程 / 上级查房 / 出院记录 /
术前小结 / 手术记录 / 术后病程，共 7 个。

依赖方向：本模块 → _render_common（只 import 通用渲染器与 _v，不 import record_renderer）。
"""

from __future__ import annotations

from app.services.ai._render_common import (
    _render_bracketed_sections,
    _render_flat_paragraphs,
    _v,
)


# ─── 7 个病程类 render 函数（薄壳，复用通用渲染器） ─────────────────


def render_first_course_record(data: dict, **_extra) -> str:
    """首次病程记录：3 章节 + 首行标题。"""
    return _render_bracketed_sections(
        data,
        [
            ("case_summary", "【病例特点】"),
            ("diagnosis_discussion", "【拟诊讨论】"),
            ("treatment_plan", "【诊疗计划】"),
        ],
        title_line="首次病程记录\n（书写时间：入院后__小时内完成）",
    )


def render_course_record(data: dict, **_extra) -> str:
    """日常病程记录：6 个平铺段落。"""
    return _render_flat_paragraphs(
        data,
        [
            ("patient_complaint", "患者病情记录"),
            ("physical_exam_today", "查体"),
            ("auxiliary_results", "辅助检查结果回报"),
            ("case_analysis", "病情分析"),
            ("treatment_adjustment", "诊疗措施及调整"),
            ("precautions", "注意事项"),
        ],
        title_line="____年__月__日 __:__ 病程记录",
    )


def render_senior_round(data: dict, **_extra) -> str:
    """上级医师查房记录：3 个平铺段落 + 首行 + 末行签名。"""
    body = _render_flat_paragraphs(
        data,
        [
            ("history_supplement", "患者病史补充"),
            ("case_analysis", "病情分析"),
            ("treatment_advice", "诊疗意见"),
        ],
        title_line="____年__月__日 __:__ 上级医师查房记录\n查房医师：____（主治/副主任/主任医师）  职称：____",
    )
    return body + "\n\n查房医师签名：____"


def render_discharge_record(data: dict, **_extra) -> str:
    """出院记录：7 章节。"""
    return _render_bracketed_sections(
        data,
        [
            ("chief_complaint", "【主诉】"),
            ("admission_status", "【入院情况】"),
            ("admission_diagnosis", "【入院诊断】"),
            ("treatment_course", "【诊疗经过】"),
            ("discharge_status", "【出院情况】"),
            ("discharge_diagnosis", "【出院诊断】"),
            ("discharge_advice", "【出院医嘱】"),
        ],
        title_line="出院记录",
    )


def render_pre_op_summary(data: dict, **_extra) -> str:
    """术前小结：9 章节 + 末行签名块。"""
    body = _render_bracketed_sections(
        data,
        [
            ("case_brief", "【病历摘要】"),
            ("preop_diagnosis", "【术前诊断】"),
            ("surgery_indication", "【手术指征】"),
            ("surgery_plan", "【拟施手术名称及方式】"),
            ("anesthesia_plan", "【拟施麻醉方式】"),
            ("surgery_team", "【手术组成员】"),
            ("preop_preparation", "【术前准备情况】"),
            ("intraop_postop_risk", "【术中术后预计情况及预防处理措施】"),
            ("senior_advice", "【上级医师意见】"),
        ],
        title_line="术前小结",
    )
    return body + "\n\n上级医师签字：____\n经治医师签字：____\n记录日期：____年__月__日 __时__分"


def render_op_record(data: dict, **_extra) -> str:
    """手术记录：元数据头 + 2 个【】章节 + 末行签名。"""
    header_lines = [
        "手术记录",
        "",
        f"手术日期：{_v(data, 'surgery_date')}",
        f"手术开始时间：{_v(data, 'surgery_start_time')}",
        f"手术结束时间：{_v(data, 'surgery_end_time')}",
        f"术前诊断：{_v(data, 'preop_diagnosis')}",
        f"术后诊断：{_v(data, 'postop_diagnosis')}",
        f"手术名称：{_v(data, 'surgery_name')}",
        f"手术医师：{_v(data, 'surgery_team')}",
        f"麻醉：{_v(data, 'anesthesia')}",
        f"护士：{_v(data, 'nurses')}",
    ]
    body_sections = _render_bracketed_sections(
        data,
        [
            ("surgery_process", "【手术经过】"),
            ("intraop_status", "【术中情况】"),
        ],
    )
    return "\n".join(header_lines) + "\n\n" + body_sections + "\n\n术者签名：____\n记录医师：____\n记录日期：____年__月__日"


def render_post_op_record(data: dict, **_extra) -> str:
    """术后病程记录：6 章节 + 首行 + 末行签名。"""
    body = _render_bracketed_sections(
        data,
        [
            ("patient_complaint", "【患者主诉】"),
            ("physical_exam_today", "【查体】"),
            ("auxiliary_results", "【辅助检查结果回报】"),
            ("recovery_assessment", "【病情分析及术后恢复情况评估】"),
            ("treatment_measures", "【诊疗措施】"),
            ("next_plan", "【注意事项及下一步计划】"),
        ],
        title_line="____年__月__日 __:__  术后病程记录（术后第__天）\n查房医师：____（主治/主任医师）",
    )
    return body + "\n\n记录医师：____"
