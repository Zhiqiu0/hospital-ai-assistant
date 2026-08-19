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

# 住院系 schema 已拆至独立文件；此处导入既供 SCHEMA_MAP 路由，
# 也保持 record_schemas.X 的对外导入路径不变（renderer/测试在用）
from app.services.ai.record_schemas_inpatient import (  # noqa: F401
    ADMISSION_NOTE_SCHEMA,
    COURSE_RECORD_SCHEMA,
    DISCHARGE_RECORD_SCHEMA,
    FIRST_COURSE_SCHEMA,
    OP_RECORD_SCHEMA,
    POST_OP_RECORD_SCHEMA,
    PRE_OP_SUMMARY_SCHEMA,
    SENIOR_ROUND_SCHEMA,
)


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
    # 剥掉 LLM 偶发的整段包裹引号（主诉改写试验中出现过 "“胃痛反复发作”"）：
    # 仅当首尾是成对引号、且剥掉后内部不再含同款引号时才剥一层，
    # 避免误伤正文里的合法引用（如 否认"发热患者"接触史）
    for lq, rq in (("\u201c", "\u201d"), ('"', '"'), ("\u2018", "\u2019")):
        if len(text) > 2 and text.startswith(lq) and text.endswith(rq):
            inner = text[1:-1]
            if lq not in inner and rq not in inner:
                text = inner.strip()
            break
    return text if text else default


def sanitize_inline_field(value, default: str = PLACEHOLDER, max_len: int = 64) -> str:
    """单行身份类字段（患者姓名/性别/年龄等）的 prompt 注入清洗（2026-06-11）。

    这些字段会被直接 format 进 prompt 模板的行结构里，恶意或异常输入中的
    换行/回车/空字符可以伪造新的 prompt 段落（prompt 注入面）。
    与 coalesce_field 的区别：本函数会压平换行 + 截断超长——只能用于
    天然单行的短字段，**不要**用于现病史等合法多行内容。
    """
    text = coalesce_field(value, default)
    if text == default:
        return text
    # 换行/回车/制表/空字符统一压成单空格，再合并连续空格
    text = text.replace("\x00", "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = " ".join(text.split())
    # 身份字段超长基本是异常输入（正常姓名/年龄远小于 64 字符），截断防 prompt 膨胀
    if len(text) > max_len:
        text = text[:max_len]
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
    "chief_complaint": "主诉（把医生口语规范化为医学书面语，如'胸口'→'胸部'、'拉肚子'→'腹泻'；症状/部位/侧别/持续时间/数值必须与医生录入完全一致：没写侧别绝不添加左右、模糊时间写'10天余/数天/3-4天'禁止编精确数、'39度'等数值必须保留；不得把症状改成诊断名，医生原文是诊断名的复诊主诉照抄；20 字以内）",
    "history_present_illness": "现病史（口语转书面医学语言，含起病/演变/诊治经过/一般情况）",
    "past_history": "既往史（既往病史/手术史/长期用药史/育龄期女性月经史；空写'否认'）",
    "allergy_history": "过敏史（食物/药物过敏；空写'否认药物及食物过敏史'）",
    "personal_history": "个人史（生活习惯/烟酒/职业暴露等）",
    # 家族史（2026-08-19 对照濮氏门诊病历补齐）：医院门诊模板有家族史栏，
    # 患者档案本就存有该字段并随请求下发，此前门诊生成没用上
    "family_history": "家族史（直系亲属重要疾病史；照抄医生录入，空写 [未填写，需补充]）",
    "physical_exam_vitals": (
        "生命体征行（按 'T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg' 一整行格式输出，"
        "严格照抄医生录入的体征数据；全部为空写 [未填写，需补充]）"
    ),
    "tcm_inspection": "中医望诊（神色形态；把医生录入整理成书面语，不加事实，空写 [未填写，需补充]）",
    "tcm_auscultation": "中医闻诊（语声/气味；把医生录入整理成书面语，不加事实，空写 [未填写，需补充]）",
    "tongue_coating": "舌象（舌质+舌苔，如'舌淡红苔薄白'；照抄医生录入，空写 [未填写，需补充]）",
    "pulse_condition": "脉象（如'脉弦细''脉滑数'；照抄医生录入，空写 [未填写，需补充]）",
    "physical_exam_text": "其余阳性体征（除生命体征/中医四诊外的体格检查文字描述）",
    # 辨证分析（2026-08-19 对照濮氏门诊病历补齐）：医院门诊模板"中医四诊及辩证分析"
    # 段在四诊后带一整段辨证分析，与住院首次病程的中医辨证依据同款写法
    "tcm_syndrome_analysis": (
        "辨证分析（结构：病因病机分析→'故见…'→'舌…脉…，均为X之征'。"
        "只能引用医生录入的症状/体征/舌脉原词，不得添加录入中没有的证候描述"
        "（如'痛有定处/入夜尤甚'）；医生未录入中医诊断则整段写 [未填写，需补充]）"
    ),
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
