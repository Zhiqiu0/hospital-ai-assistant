"""
病历模板渲染器（services/ai/record_renderer.py）

L3 治本路线核心组件——把 LLM 返回的字段 dict 按统一模板拼成展示文本。

为什么需要：
  之前 LLM 直接输出病历正文，自由发挥导致行格式偏离 prompt 契约
  （如把"切诊·脉象：xxx"写成"切诊：xxx"，把舌象塞进望诊行），
  导致 QC 规则和前端行级写入找不到对应字段误报"未填写"。

  新架构下 LLM 只填字段值（chat_json_stream 拿 JSON），由本模块
  按章节级 / 子行级模板严格拼装，输出 100% 符合：
    - 后端 _SECTION_LINE_PREFIXES 解析逻辑
    - 前端 FIELD_TO_LINE_PREFIX 行级写入逻辑
    - QC 完整性规则的 §章节名 匹配

测试：tests/test_record_renderer.py 对每个 render_* 函数断言输出符合契约。
"""

from __future__ import annotations

from typing import Optional

from app.services.ai.record_schemas import PLACEHOLDER, coalesce_field


# ─── 共享 helpers ───────────────────────────────────────────────────


def _v(data: dict, key: str, default: str = PLACEHOLDER) -> str:
    """从 data 取字段值，空值 / 非字符串兜底为 default（薄壳，复用 coalesce_field）。"""
    return coalesce_field(data.get(key), default)


def _section(header: str, body: str) -> str:
    """章节级拼装：'【XXX】\\n{body}'，body 已是规范化文本。"""
    return f"{header}\n{body}"


def _subline(prefix: str, value: str) -> str:
    """子行拼装：'{prefix}{value}'。prefix 自带冒号（如 '望诊：' / '· 疼痛评估：'）。"""
    return f"{prefix}{value}"


def _merge_tcm_diagnosis(disease: str, syndrome: str) -> str:
    """中医诊断合并行：'X — Y' 格式。

    与 prompt 契约 + completeness_rules._split_tcm_diagnosis 一致：
      - 两项都填  → 'X — Y'（破折号是 em-dash，前后留空格）
      - 仅疾病    → 'X'（让 §中医证候诊断 规则正确报缺）
      - 仅证候    → '[未填写，需补充] — Y'（让 §中医疾病诊断 报缺，
                                            但医生看到的是占位符而不是孤立的 '— Y'）
      - 都未填    → '[未填写，需补充]'
    """
    has_disease = disease and disease != PLACEHOLDER
    has_syndrome = syndrome and syndrome != PLACEHOLDER
    if has_disease and has_syndrome:
        return f"{disease} — {syndrome}"
    if has_disease:
        return disease
    if has_syndrome:
        return f"{PLACEHOLDER} — {syndrome}"
    return PLACEHOLDER


# ─── 门诊（中医） ────────────────────────────────────────────────────


def render_outpatient(
    data: dict,
    *,
    visit_time: Optional[str] = None,
    onset_time: Optional[str] = None,
    **_extra,
) -> str:
    """渲染门诊病历文本。

    输入 data 里需要的字段见 record_schemas.OUTPATIENT_SCHEMA。
    visit_time / onset_time 是请求层元数据（非 LLM 输出），首行展示用。

    输出严格符合契约：
      - 【体格检查】首行是 'T:...' 生命体征
      - 中医四诊 4 行用 '望诊：' / '闻诊：' / '切诊·舌象：' / '切诊·脉象：' 子行
      - 【诊断】用 '中医诊断：X — Y' / '西医诊断：xxx' 子行
      - 【治疗意见及措施】用 '治则治法：' / '处理意见：' / '复诊建议：' / '注意事项：' 子行
    """
    parts: list[str] = []

    # 首行元数据（与原 prompt 契约一致）
    if visit_time or onset_time:
        parts.append(
            f"就诊时间：{visit_time or '未记录'}　病发时间：{onset_time or '未记录'}"
        )

    # 主诉/现病史/既往史/过敏史/个人史 — 章节级整段
    parts.append(_section("【主诉】", _v(data, "chief_complaint")))
    parts.append(_section("【现病史】", _v(data, "history_present_illness")))
    parts.append(_section("【既往史】", _v(data, "past_history")))
    parts.append(_section("【过敏史】", _v(data, "allergy_history")))
    parts.append(_section("【个人史】", _v(data, "personal_history")))

    # 体格检查 — 多行子结构
    pe_lines = [
        _v(data, "physical_exam_vitals"),  # 生命体征行（已是 'T:...' 格式）
        _subline("望诊：", _v(data, "tcm_inspection")),
        _subline("闻诊：", _v(data, "tcm_auscultation")),
        _subline("切诊·舌象：", _v(data, "tongue_coating")),
        _subline("切诊·脉象：", _v(data, "pulse_condition")),
        _subline("其余阳性体征：", _v(data, "physical_exam_text")),
    ]
    parts.append(_section("【体格检查】", "\n".join(pe_lines)))

    # 辅助检查 — 章节级，无内容写"暂无"（与 prompt 契约一致，不写占位符）
    aux = data.get("auxiliary_exam")
    aux_text = (str(aux).strip() if aux else "") or "暂无"
    parts.append(_section("【辅助检查】", aux_text))

    # 诊断 — 中医诊断合并行 + 西医诊断子行
    tcm_line = _merge_tcm_diagnosis(
        _v(data, "tcm_disease_diagnosis"),
        _v(data, "tcm_syndrome_diagnosis"),
    )
    diagnosis_lines = [
        _subline("中医诊断：", tcm_line),
        _subline("西医诊断：", _v(data, "western_diagnosis")),
    ]
    parts.append(_section("【诊断】", "\n".join(diagnosis_lines)))

    # 治疗意见及措施 — 4 个子行
    # 注意事项可空（prompt 里 conditional 注入），按现状只在有值时显示该行
    treatment_lines = [
        _subline("治则治法：", _v(data, "treatment_method")),
        _subline("处理意见：", _v(data, "treatment_plan")),
        _subline("复诊建议：", _v(data, "followup_advice")),
    ]
    precautions_val = data.get("precautions")
    if precautions_val and str(precautions_val).strip():
        treatment_lines.append(_subline("注意事项：", str(precautions_val).strip()))
    parts.append(_section("【治疗意见及措施】", "\n".join(treatment_lines)))

    return "\n\n".join(parts)


# ─── 急诊 ────────────────────────────────────────────────────────────


def render_emergency(
    data: dict,
    *,
    visit_time: Optional[str] = None,
    onset_time: Optional[str] = None,
    **_extra,
) -> str:
    """渲染急诊病历文本。

    输入字段见 record_schemas.EMERGENCY_SCHEMA。
    急诊不含中医四诊，体格检查段只有"T: 生命体征"+"重点体征"两行。

    输出严格符合契约：
      - 【体格检查】首行是 'T:...' 生命体征
      - 【急诊处置】/【患者去向】/（可选）【急诊留观记录】 都是独立章节
      - observation_notes 有值才渲染【急诊留观记录】章节，否则跳过
    """
    parts: list[str] = []

    if visit_time or onset_time:
        parts.append(
            f"就诊时间：{visit_time or '未记录'}　病发时间：{onset_time or '未记录'}"
        )

    parts.append(_section("【主诉】", _v(data, "chief_complaint")))
    parts.append(_section("【现病史】", _v(data, "history_present_illness")))
    parts.append(_section("【既往史】", _v(data, "past_history")))
    parts.append(_section("【过敏史】", _v(data, "allergy_history")))

    # 体格检查 — 生命体征行 + 重点体征行
    pe_lines = [
        _v(data, "physical_exam_vitals"),
        _subline("重点体征：", _v(data, "physical_exam_text")),
    ]
    parts.append(_section("【体格检查】", "\n".join(pe_lines)))

    # 辅助检查 — 空写"暂无"
    aux = data.get("auxiliary_exam")
    aux_text = (str(aux).strip() if aux else "") or "暂无"
    parts.append(_section("【辅助检查】", aux_text))

    parts.append(_section("【诊断】", _v(data, "diagnosis")))
    parts.append(_section("【急诊处置】", _v(data, "treatment_plan")))

    # 急诊留观记录 — 仅当 observation_notes 有值时才渲染该章节
    # 避免"回家观察"等无需留观的场景被 QC 误报
    obs = data.get("observation_notes")
    if obs and str(obs).strip():
        parts.append(_section("【急诊留观记录】", str(obs).strip()))

    parts.append(_section("【患者去向】", _v(data, "patient_disposition")))

    return "\n\n".join(parts)


# ─── 住院入院记录 ────────────────────────────────────────────────────


# 专项评估 7 子行的字段名 → 子行前缀（与 _SECTION_LINE_PREFIXES 一致）
_ASSESSMENT_LINES = [
    ("pain_assessment", "· 疼痛评估（NRS评分）："),
    ("vte_risk", "· VTE风险："),
    ("nutrition_assessment", "· 营养风险："),
    ("psychology_assessment", "· 心理状态："),
    ("rehabilitation_assessment", "· 康复需求："),
    ("current_medications", "· 当前用药："),
    ("religion_belief", "· 宗教信仰/饮食禁忌："),
]


def render_admission_note(
    data: dict,
    *,
    patient_gender: Optional[str] = None,
    **_extra,
) -> str:
    """渲染住院入院记录文本。

    含 11 个章节 + 专项评估 7 子行 + 体格检查"T:"生命体征行。
    月经史章节仅女性患者输出（与 prompt 契约一致）。
    """
    parts: list[str] = []
    parts.append(_section("【主诉】", _v(data, "chief_complaint")))
    parts.append(_section("【现病史】", _v(data, "history_present_illness")))
    parts.append(_section("【既往史】", _v(data, "past_history")))
    parts.append(_section("【个人史】", _v(data, "personal_history")))
    parts.append(_section("【婚育史】", _v(data, "marital_history")))

    # 月经史：仅女性患者输出（男性患者跳过）
    if (patient_gender or "").strip() in {"女", "female"}:
        parts.append(_section("【月经史】", _v(data, "menstrual_history")))

    parts.append(_section("【家族史】", _v(data, "family_history")))
    parts.append(_section("【病史陈述者】", _v(data, "history_informant")))

    # 专项评估 — 7 子行
    assessment_lines = [
        _subline(prefix, _v(data, key)) for key, prefix in _ASSESSMENT_LINES
    ]
    parts.append(_section("【专项评估】", "\n".join(assessment_lines)))

    # 体格检查 — 生命体征行 + 文字描述
    pe_lines = [
        _v(data, "physical_exam_vitals"),
        _v(data, "physical_exam_text"),
    ]
    parts.append(_section("【体格检查】", "\n".join(pe_lines)))

    parts.append(_section("【辅助检查（入院前）】", _v(data, "auxiliary_exam")))
    parts.append(_section("【入院诊断】", _v(data, "admission_diagnosis")))
    return "\n\n".join(parts)


# ─── 通用"章节级整段"渲染器（病程类） ───────────────────────────────


def _render_bracketed_sections(
    data: dict, sections: list[tuple[str, str]],
    *,
    title_line: Optional[str] = None,
) -> str:
    """通用渲染：每个字段对应一个【XXX】章节，按顺序拼接。

    Args:
        data: LLM 返回的字段 dict
        sections: [(field_name, '【章节标题】'), ...] 顺序敏感
        title_line: 可选首行标题（如"首次病程记录\\n（书写时间：入院后__小时内完成）"）

    用于首次病程 / 出院记录 / 术前小结 / 术后病程 等"全是 bracket 章节"的 record_type。
    """
    parts: list[str] = []
    if title_line:
        parts.append(title_line)
    for field, header in sections:
        parts.append(_section(header, _v(data, field)))
    return "\n\n".join(parts)


def _render_flat_paragraphs(
    data: dict, fields: list[tuple[str, str]],
    *,
    title_line: Optional[str] = None,
) -> str:
    """通用渲染：每个字段输出 "{title}：{value}" 平铺段落（无【】章节）。

    用于日常病程 / 上级查房 这类"流水账文字 prompt"的 record_type。
    """
    parts: list[str] = []
    if title_line:
        parts.append(title_line)
    for field, title in fields:
        parts.append(f"{title}：\n{_v(data, field)}")
    return "\n\n".join(parts)


# ─── 7 个病程类 render 函数（薄壳，复用上面通用渲染器） ─────────────


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


# ─── 公共入口 ────────────────────────────────────────────────────────


# record_type → render 函数的路由表（注册式，新增 record_type 在这加一行即可）
_RENDERERS = {
    "outpatient": render_outpatient,
    "emergency": render_emergency,
    "admission_note": render_admission_note,
    "first_course_record": render_first_course_record,
    "course_record": render_course_record,
    "senior_round": render_senior_round,
    "discharge_record": render_discharge_record,
    "pre_op_summary": render_pre_op_summary,
    "op_record": render_op_record,
    "post_op_record": render_post_op_record,
}


def render_record(record_type: str, data: dict, **meta) -> str:
    """按 record_type 路由到对应渲染器。

    Args:
        record_type: 见 _RENDERERS 注册表
        data: LLM 返回的字段 dict（key 必须在对应 schema 内）
        **meta: 渲染器需要的请求层元数据（visit_time / onset_time / patient_gender 等，
                未被某个 renderer 用到的会被 **_extra 吃掉）

    Raises:
        NotImplementedError: record_type 不在注册表（路由层应用 NEW_ARCH_RECORD_TYPES 白名单过滤）。
    """
    renderer = _RENDERERS.get(record_type)
    if renderer is None:
        raise NotImplementedError(f"record_type={record_type!r} 未注册渲染器")
    return renderer(data, **meta)
