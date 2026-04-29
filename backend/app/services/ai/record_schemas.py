"""
病历生成结构化输出 Schema 定义（services/ai/record_schemas.py）

目的（L3 治本路线）：
  把 LLM 病历生成从"自由文本输出"改成"结构化 JSON 输出"——
  LLM 只填字段值，不再自由发挥行格式。后端用 record_renderer 按
  统一模板拼成展示文本，行格式 100% 受控、永远符合 QC 契约。

  根除问题：之前 LLM 偶尔写"切诊：脉弦"（应是"切诊·脉象：脉弦"）、
  把舌象塞进望诊行，导致 QC 误报"未填写"。新架构下 LLM 不再产出
  这些行，由后端 renderer 严格按契约拼装。

每个 record_type 对应一份字段表：{字段名: 中文描述}。
描述用于注入 prompt，告诉 LLM 每个 key 的语义。
"""

from __future__ import annotations


# ── 占位符常量（与前端 qcFieldMaps + 后端 _PLACEHOLDER_VALUES 一致）──
# 任何字段空值统一渲染为该占位符，QC 规则会识别并报"未填写"。
PLACEHOLDER = "[未填写，需补充]"


def coalesce_field(value, default: str = PLACEHOLDER) -> str:
    """LLM 返回字段值的统一兜底——空值 / 非字符串 → 占位符。

    防御 LLM 偶尔违反 prompt 契约返回非字符串（dict/list/数字）时把
    JSON 字面量直接塞进病历正文的尴尬。供 record_renderer 渲染层和
    record_prompts 注入层共用，避免双份实现漂移。
    """
    if value is None:
        return default
    # LLM 应该只返回字符串，但 prompt 偶尔失守——非 str/数字一律退回占位符
    if not isinstance(value, (str, int, float)):
        return default
    text = str(value).strip()
    return text if text else default


# record_type → 中文标签（唯一权威映射，prompt / QC / 评分 共用）。
# 从 prompts_generation.py 迁来——L3 阶段 4 删除老 prompt 文件后，
# 这个映射作为 schema 层基础常量保留。
RECORD_TYPE_LABELS: dict[str, str] = {
    "outpatient": "门诊病历",
    "emergency": "急诊病历",
    "admission_note": "入院记录",
    "first_course_record": "首次病程记录",
    "course_record": "日常病程记录",
    "senior_round": "上级医师查房记录",
    "discharge_record": "出院记录",
    "pre_op_summary": "术前小结",
    "op_record": "手术记录",
    "post_op_record": "术后病程记录",
}


# ─── 门诊（中医） — outpatient ───────────────────────────────────────
#
# 体格检查段在 renderer 内拼接成多行（T: 生命体征 + 望/闻/切·舌/切·脉 + 其余阳性体征），
# 所以 schema 里把生命体征 / 中医四诊 / 其余阳性体征拆成独立 key，
# 各自独立填值，让 LLM 一字段一格。
OUTPATIENT_SCHEMA: dict[str, str] = {
    "chief_complaint": "主诉（症状/体征+持续时间，20 字以内，原则上不用诊断名称）",
    "history_present_illness": "现病史（口语转书面医学语言，含起病/演变/诊治经过/一般情况）",
    "past_history": "既往史（既往病史/手术史/长期用药史/育龄期女性月经史；空写'否认'）",
    "allergy_history": "过敏史（食物/药物过敏；空写'否认药物及食物过敏史'）",
    "personal_history": "个人史（生活习惯/烟酒/职业暴露等）",
    "physical_exam_vitals": (
        "生命体征行（按 'T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg' 一整行格式输出，"
        "严格照抄医生录入的体征数据；全部为空写 [未填写，需补充]）"
    ),
    "tcm_inspection": "中医望诊（神色形态；照抄医生录入，空写 [未填写，需补充]）",
    "tcm_auscultation": "中医闻诊（语声/气味；照抄医生录入，空写 [未填写，需补充]）",
    "tongue_coating": "舌象（舌质+舌苔，如'舌淡红苔薄白'；照抄医生录入，空写 [未填写，需补充]）",
    "pulse_condition": "脉象（如'脉弦细''脉滑数'；照抄医生录入，空写 [未填写，需补充]）",
    "physical_exam_text": "其余阳性体征（除生命体征/中医四诊外的体格检查文字描述）",
    "auxiliary_exam": "辅助检查结果（若无则写'暂无'，不得编造）",
    "tcm_disease_diagnosis": "中医疾病诊断（如'感冒'；照抄医生录入，空写 [未填写，需补充]）",
    "tcm_syndrome_diagnosis": "中医证候诊断（如'风寒束表证'；照抄医生录入，空写 [未填写，需补充]）",
    "western_diagnosis": "西医诊断（照抄医生录入，空写 [未填写，需补充]）",
    "treatment_method": "治则治法（如'疏风散寒'；照抄医生录入，空写 [未填写，需补充]）",
    "treatment_plan": "处理意见（用药/医嘱；照抄医生录入，空写 [未填写，需补充]）",
    "followup_advice": "复诊建议（如'1周后复诊'；照抄医生录入，空写 [未填写，需补充]）",
    "precautions": "注意事项（饮食/活动/用药等注意；可空，空时不渲染该子行）",
}


# ─── 急诊 — emergency ────────────────────────────────────────────────
#
# 急诊不需要中医四诊；增加留观记录 / 患者去向。
EMERGENCY_SCHEMA: dict[str, str] = {
    "chief_complaint": "主诉",
    "history_present_illness": "现病史（①起病时间/诱因/主要症状及演变 ②院前处置经过 ③一般情况）",
    "past_history": "既往史（无则写'否认'）",
    "allergy_history": "过敏史（无则写'否认药物及食物过敏史'）",
    "physical_exam_vitals": (
        "生命体征行（'T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg' 一整行；"
        "缺项写'[未测]'；全部为空写 [未填写，需补充]）"
    ),
    "physical_exam_text": "重点体征（除生命体征外的体格检查文字描述）",
    "auxiliary_exam": "辅助检查（若无则'暂无'，禁止编造）",
    "diagnosis": "急诊诊断（照抄医生录入，空写 [未填写，需补充]）",
    "treatment_plan": "急诊处置（照抄医生录入）",
    "observation_notes": "留观记录（仅留院观察时填，可空）",
    "patient_disposition": "患者去向：回家观察/留院观察/收入住院/转院/手术室",
}


# ─── 住院入院记录 — admission_note ───────────────────────────────────
#
# 含【专项评估】7 子行（疼痛/VTE/营养/心理/康复/用药/宗教信仰），
# 在 renderer 内拼成"· 疼痛评估：xxx"等子行格式。
ADMISSION_NOTE_SCHEMA: dict[str, str] = {
    "chief_complaint": "主诉（20 字以内）",
    "history_present_illness": "现病史",
    "past_history": "既往史（重要既往病史/传染病史/手术史/家族史）",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "marital_history": "婚育史（已婚/未婚/子女情况）",
    "menstrual_history": "月经史（仅育龄期女性）",
    "family_history": "家族史（一二级亲属遗传倾向疾病）",
    "history_informant": "病史陈述者（患者本人/家属姓名+关系）",
    # 专项评估 7 子行
    "current_medications": "当前用药",
    "pain_assessment": "疼痛评估（NRS 评分 0-10）",
    "rehabilitation_assessment": "康复需求",
    "psychology_assessment": "心理状态",
    "nutrition_assessment": "营养风险",
    "vte_risk": "VTE 风险",
    "religion_belief": "宗教信仰/饮食禁忌",
    # 体格检查
    "physical_exam_vitals": "生命体征行（T:/P:/R:/BP: 一整行）",
    "physical_exam_text": "体格检查文字描述（一般情况/皮肤/淋巴结/头颈/胸/腹/四肢/神经系统等）",
    # 入院前辅查 + 诊断
    "auxiliary_exam": "辅助检查（入院前）",
    "admission_diagnosis": "入院诊断（规范术语，主要诊断放首位）",
}


# ─── 首次病程记录 — first_course_record ─────────────────────────────
#
# 章节级整段 3 个：病例特点 / 拟诊讨论 / 诊疗计划。
# 渲染时由 renderer 加首行标题"首次病程记录\n（书写时间：入院后__小时内完成）"
FIRST_COURSE_SCHEMA: dict[str, str] = {
    "case_summary": "病例特点（对病史/体格检查/辅助检查的全面归纳，禁止照抄现病史）",
    "diagnosis_discussion": (
        "拟诊讨论（①主要诊断依据 ②至少 2 个鉴别诊断及鉴别要点）"
    ),
    "treatment_plan": (
        "诊疗计划（①需进一步完善的辅助检查 ②治疗方案 ③病情观察要点）"
    ),
}


# ─── 日常病程记录 — course_record ────────────────────────────────────
#
# 平铺段落（不含【】章节标题，只用"{title}：{value}"行式段落）。
# renderer 用普通"标题：内容"格式输出。
COURSE_RECORD_SCHEMA: dict[str, str] = {
    "patient_complaint": "患者病情记录（当前主诉/症状变化）",
    "physical_exam_today": "查体（当日体征：'T:__℃ P:__次/分 R:__次/分 BP:__/__mmHg'+ 专科体征变化）",
    "auxiliary_results": "辅助检查结果回报（最新化验/检查结果及分析）",
    "case_analysis": "病情分析（演变/诊断是否需修正）",
    "treatment_adjustment": "诊疗措施及调整（当日医嘱调整及依据）",
    "precautions": "注意事项（下一步观察要点）",
}


# ─── 上级医师查房 — senior_round ─────────────────────────────────────
#
# 平铺段落（无【】章节）。
SENIOR_ROUND_SCHEMA: dict[str, str] = {
    "history_supplement": "患者病史补充（查房医师对病史/查体的补充及修正）",
    "case_analysis": (
        "病情分析（①目前诊断是否成立及依据 ②鉴别诊断意见 ③病情评估及预后判断）"
    ),
    "treatment_advice": "诊疗意见（①需完善的检查 ②治疗方案调整意见 ③注意事项及观察要点）",
}


# ─── 出院记录 — discharge_record ─────────────────────────────────────
#
# 章节级整段 7 个，与 prompt 契约 1:1。
DISCHARGE_RECORD_SCHEMA: dict[str, str] = {
    "chief_complaint": "主诉（与入院记录一致）",
    "admission_status": "入院情况（入院时主要症状/体征/辅助检查结果）",
    "admission_diagnosis": "入院诊断",
    "treatment_course": (
        "诊疗经过（住院期间检查/确诊过程/治疗方案及效果/用药/手术（如有）/病情变化及处理）"
    ),
    "discharge_status": "出院情况（出院时症状体征改善情况/一般状态）",
    "discharge_diagnosis": "出院诊断（最终诊断，主要诊断放首位）",
    "discharge_advice": (
        "出院医嘱（①带药医嘱：药名/剂量/用法/疗程 ②饮食生活注意 ③随访时间复查项目 "
        "④异常就医指征）"
    ),
}


# ─── 术前小结 — pre_op_summary ───────────────────────────────────────
#
# 章节级整段 8 个 + 手术组人员 1 个特殊行（术者/一助/二助）。
# 手术组成员字段值由 LLM 直接输出"术者：xxx  一助：xxx  二助：xxx"格式字符串。
PRE_OP_SUMMARY_SCHEMA: dict[str, str] = {
    "case_brief": "病历摘要（姓名/性别/年龄/主诉/入院经过/主要体征/辅助检查结果）",
    "preop_diagnosis": "术前诊断（规范中文诊断术语，主要诊断放首位）",
    "surgery_indication": "手术指征（具体说明手术适应证）",
    "surgery_plan": "拟施手术名称及方式",
    "anesthesia_plan": "拟施麻醉方式",
    "surgery_team": "手术组成员（'术者：xxx  一助：xxx  二助：xxx' 格式，未定时各位置写 [未填写，需补充]）",
    "preop_preparation": "术前准备情况（术前检查完善情况/特殊准备）",
    "intraop_postop_risk": "术中术后预计情况及预防处理措施（可能出现的并发症及预防措施）",
    "senior_advice": "上级医师意见（对手术必要性/方案的审核意见）",
}


# ─── 手术记录 — op_record ────────────────────────────────────────────
#
# 包含元数据头（手术日期/时间/诊断/医师/麻醉/护士）+【手术经过】+【术中情况】两章节。
# 手术日期/时间这类结构化字段由医生在请求层提供（or LLM 输出占位符让医生后填）。
OP_RECORD_SCHEMA: dict[str, str] = {
    "surgery_date": "手术日期（YYYY 年 MM 月 DD 日，未定时写 [未填写，需补充]）",
    "surgery_start_time": "手术开始时间（HH 时 MM 分）",
    "surgery_end_time": "手术结束时间（HH 时 MM 分）",
    "preop_diagnosis": "术前诊断（与术前小结一致）",
    "postop_diagnosis": "术后诊断（手术探查后明确的诊断）",
    "surgery_name": "手术名称（规范手术名称）",
    "surgery_team": "手术医师（'术者：xxx  一助：xxx  二助：xxx'）",
    "anesthesia": "麻醉方式 + 麻醉医师（'XX麻醉  麻醉医师：xxx'）",
    "nurses": "护士（'巡回护士：xxx  器械护士：xxx'）",
    "surgery_process": "手术经过（详细描述主要操作步骤、术中所见、止血缝合情况、标本处置、术毕情况）",
    "intraop_status": "术中情况（出血/输血/输液/尿量/特殊情况）",
}


# ─── 术后病程记录 — post_op_record ───────────────────────────────────
POST_OP_RECORD_SCHEMA: dict[str, str] = {
    "patient_complaint": "患者主诉（疼痛程度/部位/有无发热/恶心呕吐等不适）",
    "physical_exam_today": (
        "查体（'T:__℃ P:__次/分 R:__次/分 BP:__/__mmHg' + 伤口情况 + 专科体征）"
    ),
    "auxiliary_results": "辅助检查结果回报（术后化验/检查结果及分析）",
    "recovery_assessment": "病情分析及术后恢复情况评估（恢复是否符合预期/有无并发症迹象）",
    "treatment_measures": "诊疗措施（医嘱执行/调整及依据：抗感染/止痛/其他）",
    "next_plan": "注意事项及下一步计划（观察重点及处理计划）",
}


# ─── Schema 路由表 ───────────────────────────────────────────────────
# L3 阶段 3 全量接入：8 个 record_type schema 全部到位。
SCHEMA_MAP: dict[str, dict[str, str]] = {
    "outpatient": OUTPATIENT_SCHEMA,
    "emergency": EMERGENCY_SCHEMA,
    "admission_note": ADMISSION_NOTE_SCHEMA,
    "first_course_record": FIRST_COURSE_SCHEMA,
    "course_record": COURSE_RECORD_SCHEMA,
    "senior_round": SENIOR_ROUND_SCHEMA,
    "discharge_record": DISCHARGE_RECORD_SCHEMA,
    "pre_op_summary": PRE_OP_SUMMARY_SCHEMA,
    "op_record": OP_RECORD_SCHEMA,
    "post_op_record": POST_OP_RECORD_SCHEMA,
}


def get_schema(record_type: str) -> dict[str, str]:
    """按 record_type 取 schema 字段表；未注册的 record_type 退回门诊。"""
    return SCHEMA_MAP.get(record_type, OUTPATIENT_SCHEMA)
