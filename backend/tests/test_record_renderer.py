"""
病历模板渲染器单元测试（test_record_renderer.py）

L3 治本核心断言：
  渲染输出 100% 符合契约——后端 _SECTION_LINE_PREFIXES 和前端 FIELD_TO_LINE_PREFIX
  能解析出所有子行，QC 规则不会因为格式偏差误报"未填写"。

每个测试覆盖一个具体场景；端到端测试用 parse_sections 解析渲染输出，
验证全部虚拟章节都能被正确注册（这是契约真实性检验）。
"""
import pytest

from app.services.ai.record_renderer import (
    _merge_tcm_diagnosis,
    render_admission_note,
    render_emergency,
    render_outpatient,
    render_record,
)
from app.services.ai.record_schemas import (
    OUTPATIENT_SCHEMA,
    PLACEHOLDER,
    get_schema,
)
from app.services.rule_engine.completeness_rules import parse_sections


# ─── Fixtures ───────────────────────────────────────────────────────


# 完整门诊数据（所有字段都填，用于"happy path"断言）
FULL_OUTPATIENT = {
    "chief_complaint": "头痛3天",
    "history_present_illness": "患者于3天前出现头痛，为搏动性，部位位于前额部及后枕部，伴恶心呕吐。",
    "past_history": "糖尿病病史。",
    "allergy_history": "否认药物及食物过敏史。",
    "personal_history": "无吸烟史，偶饮酒。",
    "physical_exam_vitals": "T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg",
    "tcm_inspection": "神志清楚，面色略红，体形中等",
    "tcm_auscultation": "语声清晰，无异常气味",
    "tongue_coating": "舌淡红，苔薄白",
    "pulse_condition": "脉弦",
    "physical_exam_text": "心肺听诊未见异常，腹软无压痛",
    "auxiliary_exam": "血常规未见异常",
    "tcm_disease_diagnosis": "感冒",
    "tcm_syndrome_diagnosis": "风寒束表证",
    "western_diagnosis": "紧张型头痛",
    "treatment_method": "疏风散寒，调和营卫",
    "treatment_plan": "桂枝汤加减，3剂",
    "followup_advice": "1周后复诊",
    "precautions": "避风寒，多饮温水",
}


# ─── Schema 字段表自检 ──────────────────────────────────────────────


class TestSchemas:
    """schema 定义稳定性，防止字段被悄悄改名导致下游解析错位。"""

    def test_outpatient_schema_has_required_fields(self):
        """门诊 schema 必须包含 QC 契约依赖的所有字段。"""
        required = {
            "chief_complaint", "history_present_illness",
            "past_history", "allergy_history", "personal_history",
            "physical_exam_vitals",
            "tcm_inspection", "tcm_auscultation",
            "tongue_coating", "pulse_condition",
            "physical_exam_text",
            "auxiliary_exam",
            "tcm_disease_diagnosis", "tcm_syndrome_diagnosis",
            "western_diagnosis",
            "treatment_method", "treatment_plan", "followup_advice",
        }
        assert required.issubset(OUTPATIENT_SCHEMA.keys())

    def test_get_schema_unknown_falls_back(self):
        """未注册 record_type → 退回门诊 schema（避免上游崩溃）。"""
        assert get_schema("unknown_type") is OUTPATIENT_SCHEMA


# ─── 中医诊断合并行 helper ──────────────────────────────────────────


class TestMergeTcmDiagnosis:
    def test_both_filled(self):
        assert _merge_tcm_diagnosis("感冒", "风寒束表证") == "感冒 — 风寒束表证"

    def test_only_disease(self):
        assert _merge_tcm_diagnosis("感冒", PLACEHOLDER) == "感冒"

    def test_only_syndrome(self):
        # 仅证候 → 用 PLACEHOLDER 代替疾病位，避免医生看到孤立的 '— xxx' 像 typo
        # parse_sections 会把 PLACEHOLDER 过滤掉，让 §中医疾病诊断 规则正确报缺
        assert _merge_tcm_diagnosis(PLACEHOLDER, "风寒束表证") == f"{PLACEHOLDER} — 风寒束表证"

    def test_both_empty(self):
        assert _merge_tcm_diagnosis(PLACEHOLDER, PLACEHOLDER) == PLACEHOLDER


# ─── render_outpatient — 章节标题契约 ───────────────────────────────


class TestOutpatientSections:
    def test_all_required_headers_present(self):
        """渲染必含 prompt 契约的 9 个章节标题（与 test_prompt_contract 一致）。"""
        out = render_outpatient(FULL_OUTPATIENT)
        for header in [
            "【主诉】",
            "【现病史】",
            "【既往史】",
            "【过敏史】",
            "【个人史】",
            "【体格检查】",
            "【辅助检查】",
            "【诊断】",
            "【治疗意见及措施】",
        ]:
            assert header in out, f"渲染输出缺少章节标题：{header}"

    def test_no_independent_tcm_diagnosis_sections(self):
        """中医四诊 / 中医诊断 / 西医诊断 等绝不能成为独立章节（必须是子行）。"""
        out = render_outpatient(FULL_OUTPATIENT)
        for forbidden in ["【望诊】", "【闻诊】", "【舌象】", "【脉象】", "【生命体征】", "【中医诊断】", "【西医诊断】"]:
            assert forbidden not in out, f"非法独立章节：{forbidden}"


# ─── render_outpatient — 子行格式契约 ───────────────────────────────


class TestOutpatientSublineContract:
    def test_physical_exam_first_line_is_vitals(self):
        """【体格检查】首行必须以 'T:' 起头（前端行级写入锚点）。"""
        out = render_outpatient(FULL_OUTPATIENT)
        # 抽出【体格检查】到下一个【】之间
        start = out.index("【体格检查】") + len("【体格检查】\n")
        end = out.index("【辅助检查】")
        body = out[start:end].strip()
        first_line = body.split("\n", 1)[0].strip()
        assert first_line.startswith("T:"), f"体格检查首行不是 T: ：{first_line!r}"

    def test_tcm_four_diagnoses_subline_prefixes(self):
        """中医四诊 4 个子行前缀严格符合契约（与 _SECTION_LINE_PREFIXES 一致）。"""
        out = render_outpatient(FULL_OUTPATIENT)
        for prefix in ["望诊：", "闻诊：", "切诊·舌象：", "切诊·脉象："]:
            assert prefix in out, f"缺少子行前缀：{prefix}"

    def test_tcm_diagnosis_merged_format(self):
        """【诊断】内必须含'中医诊断：X — Y' 合并行。"""
        out = render_outpatient(FULL_OUTPATIENT)
        assert "中医诊断：感冒 — 风寒束表证" in out
        assert "西医诊断：紧张型头痛" in out

    def test_treatment_sublines(self):
        """【治疗意见及措施】4 个子行前缀。"""
        out = render_outpatient(FULL_OUTPATIENT)
        assert "治则治法：疏风散寒，调和营卫" in out
        assert "处理意见：桂枝汤加减，3剂" in out
        assert "复诊建议：1周后复诊" in out
        assert "注意事项：避风寒，多饮温水" in out


# ─── 占位符兜底 ──────────────────────────────────────────────────────


class TestPlaceholders:
    def test_empty_string_falls_back_to_placeholder(self):
        """空串字段 → 占位符。"""
        data = dict(FULL_OUTPATIENT, chief_complaint="")
        out = render_outpatient(data)
        assert "【主诉】\n[未填写，需补充]" in out

    def test_none_falls_back_to_placeholder(self):
        """None 字段 → 占位符。"""
        data = dict(FULL_OUTPATIENT, tongue_coating=None)
        out = render_outpatient(data)
        assert "切诊·舌象：[未填写，需补充]" in out

    def test_whitespace_only_falls_back_to_placeholder(self):
        """纯空白字段 → 占位符。"""
        data = dict(FULL_OUTPATIENT, pulse_condition="   ")
        out = render_outpatient(data)
        assert "切诊·脉象：[未填写，需补充]" in out

    def test_auxiliary_exam_empty_writes_暂无_not_placeholder(self):
        """辅助检查空 → '暂无'（prompt 契约特殊处理，不是 [未填写]）。"""
        data = dict(FULL_OUTPATIENT, auxiliary_exam="")
        out = render_outpatient(data)
        assert "【辅助检查】\n暂无" in out

    def test_precautions_empty_omits_subline(self):
        """注意事项空 → 不渲染该子行（保持 prompt 现状，conditional 注入）。"""
        data = dict(FULL_OUTPATIENT, precautions="")
        out = render_outpatient(data)
        assert "注意事项：" not in out

    def test_full_empty_data_renders_all_placeholders(self):
        """所有字段都空 → 所有子行都用占位符，章节结构仍完整。"""
        out = render_outpatient({})
        # 必备章节标题都在
        for header in ["【主诉】", "【体格检查】", "【诊断】", "【治疗意见及措施】"]:
            assert header in out
        # 中医四诊全是占位符
        assert "望诊：[未填写，需补充]" in out
        assert "闻诊：[未填写，需补充]" in out
        assert "切诊·舌象：[未填写，需补充]" in out
        assert "切诊·脉象：[未填写，需补充]" in out

    def test_dict_value_falls_back_to_placeholder(self):
        """LLM 偶尔违反契约返回 dict/list 时，渲染应兜底到占位符，
        而不是把 JSON 字面量字符串塞进病历正文（那样医生会看到怪文本）。"""
        data = dict(FULL_OUTPATIENT, tongue_coating={"color": "red", "coating": "white"})
        out = render_outpatient(data)
        # 不应出现 JSON 序列化文本
        assert "{'color'" not in out
        assert "color" not in out or "切诊·舌象：[未填写，需补充]" in out
        # 应回到占位符
        assert "切诊·舌象：[未填写，需补充]" in out

    def test_list_value_falls_back_to_placeholder(self):
        """LLM 返回 list 也应该兜底。"""
        data = dict(FULL_OUTPATIENT, pulse_condition=["脉弦", "脉数"])
        out = render_outpatient(data)
        assert "['脉弦'" not in out
        assert "切诊·脉象：[未填写，需补充]" in out

    def test_int_value_renders_as_string(self):
        """int/float 是合法的字符串可表示值，应该正常 str() 渲染（不兜底）。"""
        data = dict(FULL_OUTPATIENT, treatment_plan=3)
        out = render_outpatient(data)
        assert "处理意见：3" in out


# ─── 元数据首行 ──────────────────────────────────────────────────────


class TestMetadata:
    def test_visit_and_onset_time_rendered_in_first_line(self):
        out = render_outpatient(
            FULL_OUTPATIENT,
            visit_time="2026-04-29 10:00",
            onset_time="2026-04-26 08:00",
        )
        first_line = out.split("\n", 1)[0]
        assert "就诊时间：2026-04-29 10:00" in first_line
        assert "病发时间：2026-04-26 08:00" in first_line

    def test_no_metadata_skips_first_line(self):
        """两个时间都不传 → 不渲染元数据行（直接以【主诉】起头）。"""
        out = render_outpatient(FULL_OUTPATIENT)
        assert out.startswith("【主诉】")


# ─── 端到端契约：渲染 → parse_sections 解析 ─────────────────────────


class TestEndToEndContract:
    """渲染输出能被 parse_sections 正确解析回所有虚拟章节——
    这是 QC 规则能正确命中的真实性检验，比单独看字符串子串更稳。
    """

    def test_filled_record_registers_all_virtual_sections(self):
        """完整数据 → sections 含 体格检查/望诊/闻诊/舌象/脉象/生命体征/中医疾病诊断/中医证候诊断 全部。"""
        out = render_outpatient(FULL_OUTPATIENT)
        sections = parse_sections(out)
        # 主章节
        assert "体格检查" in sections
        assert "诊断" in sections
        # 体格检查段子行 → 虚拟章节（含本轮新加的"生命体征"）
        assert "生命体征" in sections
        assert sections["望诊"] == "神志清楚，面色略红，体形中等"
        assert sections["闻诊"] == "语声清晰，无异常气味"
        assert sections["舌象"] == "舌淡红，苔薄白"
        assert sections["脉象"] == "脉弦"
        # 诊断段合并行被拆解 → 虚拟章节
        assert sections["中医疾病诊断"] == "感冒"
        assert sections["中医证候诊断"] == "风寒束表证"

    def test_empty_record_no_virtual_sections_registered(self):
        """全空数据 → 所有子行都是占位符 → 虚拟章节都不注册（QC 据此报缺失）。"""
        out = render_outpatient({})
        sections = parse_sections(out)
        # 子行全是占位符 → 虚拟章节全部不注册
        for name in ["生命体征", "望诊", "闻诊", "舌象", "脉象", "中医疾病诊断", "中医证候诊断"]:
            assert name not in sections, (
                f"占位符行不应注册虚拟章节 {name}，但 sections 里出现了"
            )


# ─── render_record 路由 ────────────────────────────────────────────


class TestRenderRecordRouter:
    def test_outpatient_routes_to_render_outpatient(self):
        out = render_record("outpatient", FULL_OUTPATIENT)
        assert "【主诉】" in out
        assert "切诊·舌象：" in out

    def test_emergency_routes_to_render_emergency(self):
        out = render_record("emergency", FULL_EMERGENCY)
        assert "【急诊处置】" in out
        assert "【患者去向】" in out

    def test_unimplemented_record_type_raises(self):
        """未注册的 record_type 应明确抛 NotImplementedError 而非静默错出。"""
        with pytest.raises(NotImplementedError):
            render_record("unknown_xxx", {})


# ─── 急诊 fixture + 测试 ────────────────────────────────────────────


FULL_EMERGENCY = {
    "chief_complaint": "胸痛 2 小时",
    "history_present_illness": "患者 2 小时前突发胸痛，伴大汗。",
    "past_history": "高血压 10 年",
    "allergy_history": "否认药物及食物过敏史。",
    "physical_exam_vitals": "T:36.8℃ P:100次/分 R:22次/分 BP:90/60mmHg",
    "physical_exam_text": "心率 100，律齐，未及杂音",
    "auxiliary_exam": "心电图示 ST 段抬高",
    "diagnosis": "急性心肌梗死",
    "treatment_plan": "硝酸甘油舌下含服，立即转 CCU",
    "observation_notes": "",  # 无留观（直接收入住院）
    "patient_disposition": "收入住院",
}


class TestEmergencyRenderer:
    def test_required_sections(self):
        """急诊必须含 8 个章节；个人史不在急诊契约内。"""
        out = render_emergency(FULL_EMERGENCY)
        for header in [
            "【主诉】", "【现病史】", "【既往史】", "【过敏史】",
            "【体格检查】", "【辅助检查】", "【诊断】",
            "【急诊处置】", "【患者去向】",
        ]:
            assert header in out, f"急诊缺章节 {header}"
        # 急诊不含【个人史】（与 prompt 契约一致）
        assert "【个人史】" not in out

    def test_no_tcm_subline_in_emergency(self):
        """急诊体格检查不应有中医四诊子行（与 prompt 契约一致，急诊专注西医）。"""
        out = render_emergency(FULL_EMERGENCY)
        assert "望诊：" not in out
        assert "切诊·舌象：" not in out
        assert "切诊·脉象：" not in out

    def test_physical_exam_first_line_is_vitals(self):
        out = render_emergency(FULL_EMERGENCY)
        start = out.index("【体格检查】") + len("【体格检查】\n")
        end = out.index("【辅助检查】")
        first_line = out[start:end].strip().split("\n", 1)[0].strip()
        assert first_line.startswith("T:")

    def test_observation_notes_empty_omits_section(self):
        """无留观（observation_notes 空）→ 不渲染【急诊留观记录】章节。"""
        out = render_emergency(FULL_EMERGENCY)
        assert "【急诊留观记录】" not in out

    def test_observation_notes_filled_renders_section(self):
        """有留观内容 → 渲染【急诊留观记录】章节。"""
        data = dict(FULL_EMERGENCY, observation_notes="留观 6 小时，BP 稳定，心电图无动态变化")
        out = render_emergency(data)
        assert "【急诊留观记录】" in out
        assert "留观 6 小时" in out

    def test_disposition_is_section_not_subline(self):
        """患者去向是独立章节（前端 FIELD_TO_SECTION['患者去向']='【患者去向】'）。"""
        out = render_emergency(FULL_EMERGENCY)
        assert "【患者去向】\n收入住院" in out

    def test_empty_data_renders_all_placeholders(self):
        """全空 → 所有章节用占位符；【急诊留观记录】不渲染（observation_notes 空）。"""
        out = render_emergency({})
        for header in ["【主诉】", "【诊断】", "【急诊处置】", "【患者去向】"]:
            assert header in out
        assert "【急诊留观记录】" not in out  # 空时省略
        assert "[未填写，需补充]" in out

    def test_metadata_first_line(self):
        out = render_emergency(
            FULL_EMERGENCY,
            visit_time="2026-04-29 23:50",
            onset_time="2026-04-29 21:50",
        )
        assert out.split("\n", 1)[0].startswith("就诊时间：2026-04-29 23:50")


# ─── 入院记录 ────────────────────────────────────────────────────────


FULL_ADMISSION = {
    "chief_complaint": "胸痛 2 小时",
    "history_present_illness": "突发胸痛伴大汗",
    "past_history": "高血压 10 年",
    "personal_history": "吸烟 30 年",
    "marital_history": "已婚",
    "menstrual_history": "[未填写，需补充]",
    "family_history": "父亲冠心病",
    "history_informant": "患者本人",
    "current_medications": "氨氯地平 5mg qd",
    "pain_assessment": "3 分",
    "vte_risk": "低危",
    "nutrition_assessment": "无明显风险",
    "psychology_assessment": "稳定",
    "rehabilitation_assessment": "暂无",
    "religion_belief": "无",
    "physical_exam_vitals": "T:36.8℃ P:100次/分 R:22次/分 BP:90/60mmHg",
    "physical_exam_text": "心率 100，律齐，未及杂音",
    "auxiliary_exam": "心电图 ST 抬高",
    "admission_diagnosis": "急性心肌梗死",
}


class TestAdmissionNoteRenderer:
    def test_required_sections(self):
        out = render_admission_note(FULL_ADMISSION, patient_gender="男")
        for h in [
            "【主诉】", "【现病史】", "【既往史】", "【个人史】",
            "【婚育史】", "【家族史】", "【病史陈述者】",
            "【专项评估】", "【体格检查】", "【辅助检查（入院前）】",
            "【入院诊断】",
        ]:
            assert h in out, f"入院记录缺章节 {h}"

    def test_male_omits_menstrual_history(self):
        out = render_admission_note(FULL_ADMISSION, patient_gender="男")
        assert "【月经史】" not in out

    def test_female_includes_menstrual_history(self):
        out = render_admission_note(FULL_ADMISSION, patient_gender="女")
        assert "【月经史】" in out

    def test_assessment_seven_sublines(self):
        """专项评估 7 子行前缀都在（行级写入契约）。"""
        out = render_admission_note(FULL_ADMISSION, patient_gender="男")
        for prefix in [
            "· 疼痛评估（NRS评分）：", "· VTE风险：", "· 营养风险：",
            "· 心理状态：", "· 康复需求：", "· 当前用药：", "· 宗教信仰/饮食禁忌：",
        ]:
            assert prefix in out, f"缺专项评估子行前缀 {prefix!r}"

    def test_physical_exam_first_line_is_vitals(self):
        out = render_admission_note(FULL_ADMISSION, patient_gender="男")
        start = out.index("【体格检查】") + len("【体格检查】\n")
        end = out.index("【辅助检查（入院前）】")
        first_line = out[start:end].strip().split("\n", 1)[0].strip()
        assert first_line.startswith("T:")


# ─── 病程类批量冒烟（10 record_type 路由全过） ─────────────────────


class TestInpatientRoutesSmokeBatch:
    """住院 + 7 个病程类 render_record 路由能跑通，
    每个空 data 输入都能输出含【章节】或行式段落，不抛异常。
    """

    @pytest.mark.parametrize("record_type,expected_marker", [
        ("admission_note", "【入院诊断】"),
        ("first_course_record", "【病例特点】"),
        ("course_record", "患者病情记录"),    # 平铺段落
        ("senior_round", "诊疗意见"),         # 平铺段落
        ("discharge_record", "【出院医嘱】"),
        ("pre_op_summary", "【手术指征】"),
        ("op_record", "【手术经过】"),
        ("post_op_record", "【诊疗措施】"),
    ])
    def test_record_type_renders_without_error(self, record_type, expected_marker):
        out = render_record(record_type, {}, patient_gender="男")
        assert expected_marker in out, f"{record_type} 渲染缺关键字 {expected_marker!r}"
        # 全空数据 → 占位符（除非该 record_type 有静态文字段）
        assert PLACEHOLDER in out or "____" in out
