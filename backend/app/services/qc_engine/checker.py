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
class FrontPageData:
    """病案首页结构化数据（2026-08-21 阶段3，法定"病案首页 10 分"实装的数据源）。

    由 service 层按 encounter_id 预取（患者档案 + 接诊 + 诊断条目表），
    ctx 保持纯数据——checker 仍是同步纯函数，355 个既有 rubric 测试不受影响。
    未预取（None/默认空）时首页规则一律不触发，兼容纯文本调用方。

    Attributes:
        id_card:        身份证号（校验位/性别位/出生段互验用）
        birth_date:     出生日期 ISO 字符串（与身份证出生段互验）
        gender:         性别（male/female/unknown 或中文，与身份证性别位互验）
        blood_type:     血型（首页"其余信息"0.5分/处口径）
        admission_route: 入院途径（首页项目 1分/处口径）
        allergy_history: 药物过敏史文本（首页项目口径）
        diagnoses:      结构化诊断条目 [{category,name,code,is_primary,admission_condition}]
        loaded:         是否已预取（False = 数据缺席，一切首页规则跳过）
    """

    id_card: str = ""
    birth_date: str = ""
    gender: str = ""
    blood_type: str = ""
    admission_route: str = ""
    allergy_history: str = ""
    diagnoses: tuple = ()
    loaded: bool = False


# 明确专属中医的**治疗手段**关键词（has_tcm_treatment 用）。
#
# 两条选词纪律，都是被实际误判教出来的：
#  ① 不收「颗粒」「丸」「散」「膏」这类中西药通用剂型字——西药也有蒙脱石散
#     颗粒，误判会把西医病历判成中医病历、扣回那 15 分，正是本机制要修的问题
#     的反面；
#  ② 不收「辨证」「证型」这类**会出现在章节标题里**的词（2026-09-01 生产端到端
#     实测抓到）：门诊病历模板对所有病历都渲染【辨证分析】章节，哪怕内容是
#     「[未填写，需补充]」，标题本身也带着「辨证」二字。原实现拿它去 match 整份
#     record_text，于是每一份纯西医门诊病历都被判成中医病历——修复等于没修。
#     单元测试当时构造的文本不含模板章节标题，所以没能抓到。
TCM_TREATMENT_KEYWORDS: tuple[str, ...] = (
    "中药", "中成药", "汤剂", "水煎", "煎服", "代煎",
    "先煎", "后下", "包煎", "烊化", "冲服", "膏方",
    "针灸", "针刺", "电针", "艾灸", "推拿", "拔罐",
    "刮痧", "穴位", "耳穴", "埋线",
)


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
    # 病案首页结构化数据（2026-08-21 阶段3；未预取时 loaded=False 首页规则跳过）
    front_page: FrontPageData = field(default_factory=FrontPageData)

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

    def has_tcm_treatment(self) -> bool:
        """本次诊疗是否含中医内容——中医专项扣分的法定前提。

        为什么需要它（2026-08-31 中医语义审计）：
        《浙江省中医门、急诊病历评分标准》诊断项原文是「**有中医治疗的病历**
        无中医诊断扣 10 分」、治疗意见项原文是「**实施中医治疗的**应当遵循
        辨证论治的原则」——两处扣分都以「有/实施中医治疗」为前提。系统此前
        只豁免了急诊，把前提整个丢了，于是本院最常见的**纯西医门诊**（外科
        清创、皮肤科、五官科）会被扣掉中医诊断 10 分 + 治则治法 5 分，一份
        写得完整的清创病历只能得 87 分 → 判不合格 → 签发按钮置灰。医生要么
        编一个中医病名和证型，要么学会「别点质控直接签」——前者是病历造假，
        后者让质控体系形同虚设。

        判据取保守方向（宁可判成中医病历、宁可扣分）：只要出现任一中医要素
        就按中医病历全套判。医生想躲开中医扣分，必须一个中医字都不写，而那
        时它本来就是西医病历——正是标准原文的意思。

        Returns:
            True  : 病历里有中医诊断/证候/治则治法/舌脉，或治疗里有中医疗法
            False : 通篇没有任何中医要素，视为纯西医诊疗
        """
        if self.any_section_filled(
            "中医疾病诊断", "中医证候诊断", "治则治法",
            "舌象", "脉象", "辨证分析", "中医辨证依据",
        ):
            return True
        # 治疗手段里的中医疗法。
        # **只在治疗相关章节里搜，绝不搜全文**（2026-09-01 实测修正）：病历正文
        # 里必然含【辨证分析】【中医诊断】这类模板章节标题，拿关键词去 match 整份
        # 正文，等于每份病历都命中。判「有没有实施中医治疗」，就该看医生在治疗
        # 栏里写了什么。
        _treatment = " ".join(
            self.section(name).raw_value
            for name in ("处理意见", "治则治法", "治疗意见及措施", "医嘱")
        )
        return any(kw in _treatment for kw in TCM_TREATMENT_KEYWORDS)

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
        from app.utils.text_clean import strip_invisible
        # 与 Section.normalized 同口径：先剥不可见字符再判空，否则粘贴带进来的
        # 一个零宽空格就能让本字段冒充「已填写」（见 app/utils/text_clean.py）。
        v = strip_invisible(value).strip()
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
    front_page: Optional[FrontPageData] = None,
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
        front_page=front_page or FrontPageData(),
    )
