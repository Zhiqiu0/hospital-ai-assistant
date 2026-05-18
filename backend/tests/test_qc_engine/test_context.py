"""PatientMeta / EncounterMeta / RecordContext 单元测试。

C 方案治本核心防回归：把"什么算患者基础信息""什么算育龄期"等关键判定
锁死在类型层，确保未来扩展字段时不会重蹈"inquiry 字典串场"覆辙。
"""
import pytest

from app.services.qc_engine.checker import (
    EncounterMeta,
    PatientMeta,
    RecordContext,
    build_context,
)


# ─── PatientMeta ──────────────────────────────────────────────────


class TestPatientMeta:
    def test_default_is_empty(self):
        """空 PatientMeta：has_basic_info 返回 False。"""
        p = PatientMeta()
        assert p.has_basic_info() is False
        assert p.is_female() is False
        assert p.age_int() is None
        assert p.is_in_reproductive_age() is False

    def test_has_basic_info_requires_all_three(self):
        """姓名/性别/年龄任一缺失 → has_basic_info False。"""
        assert PatientMeta(name="张三").has_basic_info() is False
        assert PatientMeta(name="张三", gender="男").has_basic_info() is False
        assert PatientMeta(name="张三", gender="男", age="45").has_basic_info() is True

    @pytest.mark.parametrize("value", ["", " ", "\t", "  \n  "])
    def test_whitespace_only_does_not_count_as_filled(self, value):
        """纯空白不算已填——避免误把"   "当作有效姓名。"""
        p = PatientMeta(name=value, gender="男", age="45")
        assert p.has_basic_info() is False

    @pytest.mark.parametrize("gender,expected", [
        ("女", True),
        ("female", True),
        ("男", False),
        ("male", False),
        ("unknown", False),
        ("", False),
    ])
    def test_is_female(self, gender, expected):
        assert PatientMeta(gender=gender).is_female() is expected

    @pytest.mark.parametrize("age_str,expected", [
        ("45", 45),
        ("45.5", 45),
        (" 30 ", 30),
        ("", None),
        ("abc", None),
        ("not-a-number", None),
    ])
    def test_age_int(self, age_str, expected):
        assert PatientMeta(age=age_str).age_int() == expected

    @pytest.mark.parametrize("age_str,expected", [
        ("11", False),    # 太年轻
        ("12", True),     # 下限
        ("30", True),
        ("55", True),     # 上限
        ("56", False),    # 太年长
        ("", False),
    ])
    def test_is_in_reproductive_age(self, age_str, expected):
        assert PatientMeta(age=age_str).is_in_reproductive_age() is expected


# ─── EncounterMeta ────────────────────────────────────────────────


class TestEncounterMeta:
    @pytest.mark.parametrize("record_type,is_emergency,is_outpatient,is_inpatient", [
        ("outpatient", False, True, False),
        ("emergency", True, False, False),
        ("admission_note", False, False, True),
        ("course_record", False, False, True),
        ("discharge_record", False, False, True),
    ])
    def test_scope_flags(self, record_type, is_emergency, is_outpatient, is_inpatient):
        """record_type 决定 emergency/outpatient/inpatient 三个派生标志。"""
        e = EncounterMeta(record_type=record_type)
        assert e.is_emergency is is_emergency
        assert e.is_outpatient is is_outpatient
        assert e.is_inpatient is is_inpatient

    def test_is_first_visit_default(self):
        assert EncounterMeta().is_first_visit is True
        assert EncounterMeta(is_first_visit=False).is_first_visit is False


# ─── build_context 集成 ───────────────────────────────────────────


class TestBuildContext:
    def test_builds_patient_meta_from_kwargs(self):
        """build_context 把 patient_xxx 参数装到 patient_meta 对象。"""
        ctx = build_context(
            "【主诉】头痛",
            patient_name="张三",
            patient_gender="男",
            patient_age="45",
        )
        assert ctx.patient_meta.name == "张三"
        assert ctx.patient_meta.gender == "男"
        assert ctx.patient_meta.age == "45"
        assert ctx.patient_meta.has_basic_info() is True

    def test_builds_encounter_meta_from_kwargs(self):
        ctx = build_context(
            "【主诉】胸痛",
            record_type="emergency",
            is_first_visit=False,
        )
        assert ctx.encounter_meta.record_type == "emergency"
        assert ctx.encounter_meta.is_emergency is True
        assert ctx.encounter_meta.is_first_visit is False

    def test_inquiry_no_longer_contains_patient_fields(self):
        """治本核心：patient_name/gender/age 不再走 inquiry 字典。

        防回归——如果未来有人手贱把 patient_name 塞到 inquiry，至少要在测试
        层面给个明确的"不该这么用"信号。
        """
        ctx = build_context(
            "【主诉】",
            patient_name="张三",
            patient_gender="男",
            patient_age="45",
            inquiry={"chief_complaint": "头痛"},  # ← inquiry 只放问诊维度字段
        )
        # patient 字段在 patient_meta 而非 inquiry
        assert "patient_name" not in ctx.inquiry
        assert "patient_gender" not in ctx.inquiry
        assert "patient_age" not in ctx.inquiry
        # 问诊字段在 inquiry
        assert ctx.inquiry["chief_complaint"] == "头痛"

    def test_context_is_frozen(self):
        """RecordContext 是不可变值对象——评分过程中不允许 mutate。"""
        from dataclasses import FrozenInstanceError
        ctx = build_context("【主诉】")
        with pytest.raises(FrozenInstanceError):
            ctx.record_text = "x"  # type: ignore


class TestRecordContextHelpers:
    def test_section_returns_empty_when_missing(self):
        ctx = build_context("【主诉】头痛")
        s = ctx.section("不存在的章节")
        assert s.is_filled() is False

    def test_inquiry_field_filled_only_checks_inquiry(self):
        """治本：inquiry_field_filled 只查 inquiry 字典，patient_meta 字段不会泄漏过来。

        旧实现一个手贱误用 inquiry_field_filled('patient_name') 永远返回 False，
        新实现下这种误用立刻能在测试中暴露（值真的不在 inquiry 里）。
        """
        ctx = build_context(
            "【主诉】",
            patient_name="张三",
            inquiry={"chief_complaint": "头痛"},
        )
        assert ctx.inquiry_field_filled("chief_complaint") is True
        # patient_name 不在 inquiry——但开发者用错也不会泄漏 patient_meta 数据
        assert ctx.inquiry_field_filled("patient_name") is False

    def test_inquiry_field_filled_filters_placeholders(self):
        """inquiry 里的占位符也视作未填。"""
        ctx = build_context(
            "【主诉】",
            inquiry={
                "chief_complaint": "头痛",
                "past_history": "[未填写，需补充]",
                "allergy_history": "",
            },
        )
        assert ctx.inquiry_field_filled("chief_complaint") is True
        assert ctx.inquiry_field_filled("past_history") is False
        assert ctx.inquiry_field_filled("allergy_history") is False
