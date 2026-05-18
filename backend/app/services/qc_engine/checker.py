"""病历检查器（services/qc_engine/checker.py）

按 **FHIR R5 资源** 分层的评分上下文，对接 rubric 的 DeductionRule.checker。

设计核心：分层语义，杜绝"字段串场"
  对应 FHIR 标准的三个核心资源：
    PatientMeta    ≈ FHIR Patient（跨接诊的患者持久信息）
    EncounterMeta  ≈ FHIR Encounter（本次接诊的元信息）
    inquiry        ≈ FHIR Observation 集合（医生录入的问诊数据）

为什么按 FHIR 建模：
  1. 国际通用标准——HIS / 医保 / 医联体对接都用这一套语义
  2. 三资源生命周期不同：Patient 跨一辈子，Encounter 一次接诊，Observation 瞬时
  3. 未来接 HIS 时直接加字段即可，不重构架构（这就是预先按标准建模的回报）

旧实现 vs 新实现：
  旧：ctx.patient_gender + ctx.inquiry["patient_age"]——平铺 + 大袋子，
      容易"该查 patient_meta 但错查 inquiry"导致规则误判
  新：ctx.patient_meta.gender + ctx.patient_meta.age_int()——分层 + 明确语义，
      checker 永远不会"塞错袋子"
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.services.qc_engine.parser import get_section, parse_record
from app.services.qc_engine.section import Section


# ─── FHIR Patient 资源最小子集 ──────────────────────────────────────


@dataclass(frozen=True)
class PatientMeta:
    """患者基础信息（对齐 FHIR R5 Patient 资源最小子集）。

    当前接入的字段（门诊场景够用）：
      name / gender / age

    HIS / 医保接入时按 FHIR 标准追加（不破坏现有 checker）：
      birth_date      → FHIR Patient.birthDate
      identifier[]    → FHIR Patient.identifier (身份证/病案号/医保号)
      address         → FHIR Patient.address
      telecom         → FHIR Patient.telecom

    Attributes:
        name: 姓名（FHIR: name.text）
        gender: 性别——保留中文"男/女"便于规则匹配，对接 FHIR 时映射 male/female
        age: 年龄字符串（前端透传 "45" / "45.5"），用 age_int() 取整数
    """

    name: str = ""
    gender: str = ""
    age: str = ""

    def has_basic_info(self) -> bool:
        """姓名、性别、年龄都已填写——治本第一个 bug 的判定入口。"""
        return all(
            getattr(self, f).strip() for f in ("name", "gender", "age")
        )

    def is_female(self) -> bool:
        """女性判定——同时支持中文"女"和 FHIR 标准 "female"。"""
        return self.gender.strip() in ("女", "female")

    def age_int(self) -> Optional[int]:
        """把 age 字符串转 int，失败返回 None。

        支持 "45" / "45.5" / " 45 " 等输入，治本第二个 bug 的判定入口。
        """
        s = self.age.strip()
        if not s:
            return None
        try:
            return int(s.split(".")[0])
        except (ValueError, AttributeError):
            return None

    def is_in_reproductive_age(self) -> bool:
        """育龄期判定（12-55 岁）——用于"育龄期女性无月经史"规则。"""
        age = self.age_int()
        return age is not None and 12 <= age <= 55


# ─── FHIR Encounter 资源最小子集 ─────────────────────────────────────


@dataclass(frozen=True)
class EncounterMeta:
    """本次接诊的元信息（对齐 FHIR R5 Encounter 资源最小子集）。

    Attributes:
        record_type: outpatient / emergency / admission_note / course_record 等
                     对接 FHIR 时映射到 Encounter.class
        is_first_visit: 是否初诊（FHIR 通过 priorEncounter 引用判断；我们直接存）
    """

    record_type: str = "outpatient"
    is_first_visit: bool = True

    @property
    def is_emergency(self) -> bool:
        """急诊场景——_emergency_missing_vitals / _emergency_missing_disposition 用。"""
        return self.record_type == "emergency"

    @property
    def is_outpatient(self) -> bool:
        return self.record_type == "outpatient"

    @property
    def is_inpatient(self) -> bool:
        """住院类（含入院记录、病程记录、出院记录等所有住院 record_type）。"""
        return self.record_type not in ("outpatient", "emergency")


# ─── 评分上下文（FHIR 三资源化） ────────────────────────────────────


@dataclass(frozen=True)
class RecordContext:
    """评分上下文——按 FHIR R5 三资源分层。

    Attributes:
        record_text: 病历正文（用于"原文是否含某关键词"这种全局检查）
        sections: 病历章节字典（parser 解析产出，is_filled 已就绪）
        patient_meta: 患者基础信息（≈ FHIR Patient）
        encounter_meta: 接诊元信息（≈ FHIR Encounter）
        inquiry: 医生录入的问诊字段（≈ FHIR Observation 集合）
                  仅含问诊维度字段（chief_complaint 等），**不再包含**患者基础信息
    """

    record_text: str
    sections: dict[str, Section]
    patient_meta: PatientMeta = field(default_factory=PatientMeta)
    encounter_meta: EncounterMeta = field(default_factory=EncounterMeta)
    inquiry: dict[str, str] = field(default_factory=dict)

    def section(self, name: str) -> Section:
        """取章节——缺失时返回空 Section，避免规则代码写 None 判断。

        用法：
            ctx.section("现病史").is_filled()
            ctx.section("现病史").contains("起病")
        """
        return get_section(self.sections, name)

    def any_section_filled(self, *names: str) -> bool:
        """任一章节已填即返回 True。"""
        return any(self.section(name).is_filled() for name in names)

    def text_contains(self, keyword: str) -> bool:
        """病历原文是否包含关键词。"""
        return keyword in self.record_text

    def inquiry_field_filled(self, field_name: str) -> bool:
        """问诊字典里指定字段是否非空且非占位符。

        ⚠️ 注意：本方法只查问诊维度字段（chief_complaint / past_history 等）。
        患者基础信息（name/gender/age）改走 ctx.patient_meta.xxx 接口，
        不会再串到 inquiry 字典里——这是 C 方案治本的核心。
        """
        value = self.inquiry.get(field_name, "")
        if not value or not isinstance(value, str):
            return False
        from app.services.qc_engine.section import PLACEHOLDERS
        v = value.strip()
        return bool(v) and v not in PLACEHOLDERS


def build_context(
    record_text: str,
    *,
    record_type: str = "outpatient",
    is_first_visit: bool = True,
    patient_name: str = "",
    patient_gender: str = "",
    patient_age: str = "",
    inquiry: Optional[dict[str, str]] = None,
) -> RecordContext:
    """从病历正文 + 元数据构造 RecordContext。

    所有 patient_xxx / encounter_xxx 字段在这里**显式归类**到对应 dataclass，
    调用方不直接 new RecordContext——确保未来加字段时只改这一处。
    """
    return RecordContext(
        record_text=record_text,
        sections=parse_record(record_text),
        patient_meta=PatientMeta(
            name=patient_name or "",
            gender=patient_gender or "",
            age=patient_age or "",
        ),
        encounter_meta=EncounterMeta(
            record_type=record_type,
            is_first_visit=is_first_visit,
        ),
        inquiry=inquiry or {},
    )
