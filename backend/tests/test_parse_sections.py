"""
parse_sections 单元测试（Audit Round 4 增加）

核心防回归：
  1. 子行解析 — 中医四诊（望/闻/舌/脉）写在【体格检查】下，必须能被注册成虚拟章节
  2. 占位符过滤 — "[未填写，需补充]" 等视作未填写，不注册虚拟章节
  3. 与前端 FIELD_TO_LINE_PREFIX 契约一致 — 11 个字段全覆盖

修复的用户痛点：
  医生在 QC 修复时把"舌淡红，苔薄白"写到【体格检查】"切诊·舌象："行 →
  之前 sections 字典里没"舌象" key → QC 规则永远报"舌象未填" → 用户绝望。
  现在 parse_sections 自动注册 sections["舌象"] = "舌淡红，苔薄白" → §舌象 规则命中。
"""

from app.services.rule_engine.completeness_rules import parse_sections, _split_tcm_diagnosis


# ─── 样本病历（与前端 qcFieldMaps.test.ts 保持一致） ──────────────────

OUTPATIENT_RECORD_FILLED = """【主诉】
头痛3天

【体格检查】
T: 37°C。身高: 181cm。
望诊：神清，面色红润
闻诊：语声清晰
切诊·舌象：舌淡红，苔薄白
切诊·脉象：脉浮数

【诊断】
感冒相关性头痛"""

OUTPATIENT_RECORD_PLACEHOLDER = """【主诉】
头痛3天

【体格检查】
T: 37°C
望诊：[未填写，需补充]
闻诊：[未填写，需补充]
切诊·舌象：[未填写，需补充]
切诊·脉象：[未填写，需补充]"""

ADMISSION_RECORD_FILLED = """【主诉】
胸痛 2 小时

【专项评估】
· 当前用药：阿司匹林 100mg qd
· 疼痛评估（NRS评分）：3分
· 康复需求：暂无
· 心理状态：稳定
· 营养风险：无明显风险
· VTE风险：低危
· 宗教信仰/饮食禁忌：无

【体格检查】
T:36.5℃ P:78次/分"""

ADMISSION_RECORD_PLACEHOLDER = """【主诉】
胸痛 2 小时

【专项评估】
· 当前用药：[未填写，需补充]
· 疼痛评估（NRS评分）：[未填写，需补充]
· 康复需求：[未填写，需补充]
· 心理状态：[未填写，需补充]
· 营养风险：[未填写，需补充]
· VTE风险：[未填写，需补充]
· 宗教信仰/饮食禁忌：[未填写，需补充]"""


# ─── 中医四诊：子行解析 ──────────────────────────────────────────────


class TestTcmDiagnosesSubsections:
    def test_filled_four_diagnoses_registered_as_virtual_sections(self):
        """4 项中医四诊都填写时，sections 字典应包含"望诊/闻诊/舌象/脉象"虚拟章节。"""
        sections = parse_sections(OUTPATIENT_RECORD_FILLED)
        assert sections["望诊"] == "神清，面色红润"
        assert sections["闻诊"] == "语声清晰"
        assert sections["舌象"] == "舌淡红，苔薄白"
        assert sections["脉象"] == "脉浮数"

    def test_placeholder_subsections_not_registered(self):
        """所有四诊都是 [未填写，需补充] 占位符时，虚拟章节不注册（视作未填写）。"""
        sections = parse_sections(OUTPATIENT_RECORD_PLACEHOLDER)
        assert "望诊" not in sections
        assert "闻诊" not in sections
        assert "舌象" not in sections
        assert "脉象" not in sections

    def test_partial_fill_registers_only_filled(self):
        """部分填写时，只有真实内容的子行才注册成虚拟章节。"""
        text = """【体格检查】
望诊：神清
闻诊：[未填写，需补充]
切诊·舌象：舌淡红
切诊·脉象：[未填写，需补充]"""
        sections = parse_sections(text)
        assert sections["望诊"] == "神清"
        assert "闻诊" not in sections
        assert sections["舌象"] == "舌淡红"
        assert "脉象" not in sections

    def test_physical_exam_section_still_registered(self):
        """注册虚拟章节不影响原【体格检查】章节的注册。"""
        sections = parse_sections(OUTPATIENT_RECORD_FILLED)
        assert "体格检查" in sections
        assert "T: 37°C。身高: 181cm。" in sections["体格检查"]


# ─── 生命体征：子行解析（治本 fix 的关键回归保护）──────────────────────


class TestVitalSignsSubsection:
    """【体格检查】下"T:"开头的行注册成虚拟章节"生命体征"。

    回归用户报告的 bug：先点中医四诊"已写入"再点生命体征"已写入"会冲掉
    舌象/脉象——前端 physical_exam_vitals 章节级整段替换是直接原因，
    但根因是"生命体征"没有作为虚拟子行被识别，QC 规则只能落到全段关键词兜底。
    """

    def test_outpatient_vitals_registered_as_virtual_section(self):
        """门诊体格检查首行 'T:36.5℃ P:78次/分...' 注册成"生命体征"虚拟章节。

        注：_split_subsections 内部把冒号归一化（":"→"："）后存回 sections，
        断言时用归一化后的中文冒号；前端展示的原始病历不受影响。
        """
        text = """【体格检查】
T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg
望诊：神清"""
        sections = parse_sections(text)
        assert "生命体征" in sections
        # value 应该是完整的生命体征行内容（不被内部 P:/R:/BP: 误切）
        # 归一化后冒号统一成中文"："
        assert "P：78次/分" in sections["生命体征"]
        assert "BP：120/80mmHg" in sections["生命体征"]
        # 其他子行仍然正确注册
        assert sections["望诊"] == "神清"

    def test_admission_vitals_with_chinese_colon(self):
        """中文冒号"T："也应注册（_norm 归一化生效）。"""
        text = """【体格检查】
T：36.5℃ P：78次/分 R：18次/分 BP：120/80mmHg"""
        sections = parse_sections(text)
        assert "生命体征" in sections
        assert "78次/分" in sections["生命体征"]

    def test_placeholder_vitals_not_registered(self):
        """生命体征行整行是占位符 → 不注册虚拟章节（视作未填写，QC 报缺）。"""
        text = """【体格检查】
T:[未填写，需补充]
望诊：神清"""
        sections = parse_sections(text)
        # 注：这个场景下 prefix "T:" 命中，value="[未填写，需补充]" 是 placeholder
        # → 按 _PLACEHOLDER_VALUES 过滤掉，不注册"生命体征"
        assert "生命体征" not in sections

    def test_vitals_partial_not_template_placeholder(self):
        """部分填写（"T:36.5℃ P:[未测]..."）应该注册——不是整段占位符。"""
        text = """【体格检查】
T:36.5℃ P:[未测] R:18次/分 BP:120/80mmHg"""
        sections = parse_sections(text)
        assert "生命体征" in sections
        assert "[未测]" in sections["生命体征"]

    def test_no_vitals_line_no_virtual_registration(self):
        """体格检查段没有 T: 开头的行 → 不注册"生命体征"虚拟章节。"""
        text = """【体格检查】
望诊：神清
切诊·舌象：舌淡红"""
        sections = parse_sections(text)
        assert "生命体征" not in sections


# ─── 【诊断】子行：兼容 LLM 输出独立三行格式 ─────────────────────────


class TestDiagnosisSubsections:
    """LLM 偶尔会把诊断写成独立三行（中医诊断 / 中医证候诊断 / 西医诊断），
    QC 必须识别这种格式，否则医生明明填了证候诊断却被报未填（用户实证 bug）。
    """

    def test_independent_three_lines_format(self):
        """独立三行格式（用户报告的真实场景）。"""
        text = """【诊断】
西医诊断：颈椎间盘突出症
中医诊断：项痹病
中医证候诊断：气滞血瘀证"""
        sections = parse_sections(text)
        assert sections["中医证候诊断"] == "气滞血瘀证"
        assert "中医疾病诊断" in sections  # 第三阶段从"中医诊断：项痹病"拆出 disease
        assert sections["中医疾病诊断"] == "项痹病"
        assert sections["西医诊断"] == "颈椎间盘突出症"

    def test_explicit_disease_diagnosis_format(self):
        """显式格式：'中医疾病诊断：项痹病' 而非'中医诊断：项痹病'。"""
        text = """【诊断】
中医疾病诊断：项痹病
中医证候诊断：气滞血瘀证"""
        sections = parse_sections(text)
        assert sections["中医疾病诊断"] == "项痹病"
        assert sections["中医证候诊断"] == "气滞血瘀证"

    def test_merged_format_still_works(self):
        """合并行格式（renderer 当前默认输出）应继续被第三阶段拆解。"""
        text = """【诊断】
中医诊断：项痹病 — 气滞血瘀证
西医诊断：颈椎间盘突出症"""
        sections = parse_sections(text)
        assert sections["中医疾病诊断"] == "项痹病"
        assert sections["中医证候诊断"] == "气滞血瘀证"
        assert sections["西医诊断"] == "颈椎间盘突出症"

    def test_placeholder_not_registered(self):
        """占位符不注册成虚拟章节，QC 据此正确报缺。"""
        text = """【诊断】
中医证候诊断：[未填写，需补充]
西医诊断：颈椎间盘突出症"""
        sections = parse_sections(text)
        assert "中医证候诊断" not in sections
        assert sections["西医诊断"] == "颈椎间盘突出症"


# ─── 住院专项评估：子行解析 ──────────────────────────────────────────


class TestAdmissionAssessmentSubsections:
    def test_seven_assessments_registered_as_virtual_sections(self):
        """7 项专项评估都填写时，sections 字典应包含 7 个虚拟章节。"""
        sections = parse_sections(ADMISSION_RECORD_FILLED)
        assert sections["疼痛评估"] == "3分"
        assert sections["VTE风险评估"] == "低危"
        assert sections["营养评估"] == "无明显风险"
        assert sections["心理评估"] == "稳定"
        assert sections["康复评估"] == "暂无"
        assert sections["当前用药"] == "阿司匹林 100mg qd"
        assert sections["宗教信仰"] == "无"

    def test_placeholder_assessments_not_registered(self):
        """全占位符时，7 个虚拟章节都不注册。"""
        sections = parse_sections(ADMISSION_RECORD_PLACEHOLDER)
        for name in [
            "疼痛评估",
            "VTE风险评估",
            "营养评估",
            "心理评估",
            "康复评估",
            "当前用药",
            "宗教信仰",
        ]:
            assert name not in sections, f"占位符不应注册虚拟章节 {name}"

    def test_assessment_section_still_registered(self):
        """注册虚拟章节不影响原【专项评估】章节的注册。"""
        sections = parse_sections(ADMISSION_RECORD_FILLED)
        assert "专项评估" in sections


# ─── 边界场景 ────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_parent_section_no_virtual_registration(self):
        """父章节不存在时，虚拟章节不注册（不会因为字符串巧合命中）。"""
        text = """【主诉】
头痛
切诊·舌象：舌淡红"""  # 望/闻/舌/脉 散落在主诉里 — 不应被识别
        sections = parse_sections(text)
        assert "舌象" not in sections, "主诉外的字符串巧合不应触发虚拟章节"

    def test_subsection_value_with_chinese_colon(self):
        """中文冒号"："正确解析。"""
        text = """【体格检查】
切诊·舌象：舌淡红，苔薄白"""
        sections = parse_sections(text)
        assert sections["舌象"] == "舌淡红，苔薄白"

    def test_subsection_value_with_english_colon(self):
        """英文冒号":"也能正确解析（兼容医生手动改格式）。"""
        text = """【体格检查】
望诊: 神清"""
        sections = parse_sections(text)
        assert sections["望诊"] == "神清"

    def test_independent_section_with_same_name_does_not_break(self):
        """如果病历里偶然有独立【舌象】章节（旧格式），不会被覆盖也不会出错。"""
        text = """【舌象】
旧格式独立章节

【体格检查】
切诊·舌象：新格式子行"""
        sections = parse_sections(text)
        # 子行解析后会用最新的子行值覆盖（这是预期 — 让 QC 走最新的位置）
        assert sections["舌象"] == "新格式子行"

    def test_empty_text(self):
        """空文本不报错，返回空字典。"""
        assert parse_sections("") == {}

    def test_no_subsections_only_normal_sections(self):
        """没有子行的常规病历照常工作。"""
        text = "【主诉】\n头痛"
        sections = parse_sections(text)
        assert sections == {"主诉": "头痛"}

    def test_inline_subsections_same_line(self):
        """LLM 实际输出可能把所有四诊塞在同一行（句号分隔），仍要正确识别。

        这是用户真实场景：润色后的 record 把多个子行合并到一行。
        如果按行首匹配会漏识别"切诊·舌象："/"切诊·脉象："，导致 QC 误报"未填写"。
        """
        text = (
            "【体格检查】\n"
            "T:37℃。望诊：神志清，精神可。闻诊：言语清晰。"
            "切诊·舌象：舌淡红，苔薄白。切诊·脉象：脉浮数。\n"
            "【诊断】\n感冒"
        )
        sections = parse_sections(text)
        assert sections["望诊"] == "神志清，精神可"
        assert sections["闻诊"] == "言语清晰"
        assert sections["舌象"] == "舌淡红，苔薄白"
        assert sections["脉象"] == "脉浮数"

    def test_inline_assessment_same_line(self):
        """专项评估 7 项也可能被 LLM 写在同一行/几行混杂。"""
        text = (
            "【专项评估】\n"
            "· 当前用药：阿司匹林。· 疼痛评估（NRS评分）：3分。· 康复需求：暂无。"
            "· 心理状态：稳定。· 营养风险：低。· VTE风险：低危。· 宗教信仰/饮食禁忌：无"
        )
        sections = parse_sections(text)
        assert sections["当前用药"] == "阿司匹林"
        assert sections["疼痛评估"] == "3分"
        assert sections["康复评估"] == "暂无"
        assert sections["心理评估"] == "稳定"
        assert sections["营养评估"] == "低"
        assert sections["VTE风险评估"] == "低危"
        assert sections["宗教信仰"] == "无"


# ─── 中医诊断合并行：拆解 → 虚拟章节 ────────────────────────────────


class TestTcmDiagnosisSplit:
    """LLM 把"中医疾病诊断 + 中医证候诊断"合并写成一行，需要拆成两个虚拟章节。

    用户痛点：医生在表单里分别填了"感冒"+"风寒束表证"，LLM 生成
    "中医诊断：感冒（风寒束表证）" → QC 规则按 §中医证候诊断 找独立章节找不到 → 误报"未填写"。
    """

    def test_paren_chinese_format(self):
        """中文括号格式：'中医诊断：感冒（风寒束表证）' — 用户截图实际场景。"""
        text = "【诊断】\n中医诊断：感冒（风寒束表证）\n西医诊断：感冒相关性头痛"
        sections = parse_sections(text)
        assert sections["中医疾病诊断"] == "感冒"
        assert sections["中医证候诊断"] == "风寒束表证"

    def test_paren_english_format(self):
        """英文括号格式：'中医诊断：眩晕病(肝阳上亢证)'。"""
        text = "【诊断】\n中医诊断:眩晕病(肝阳上亢证)"
        sections = parse_sections(text)
        assert sections["中医疾病诊断"] == "眩晕病"
        assert sections["中医证候诊断"] == "肝阳上亢证"

    def test_em_dash_format(self):
        """破折号格式：prompt 推荐写法 '中医诊断：胸痹 — 痰浊壅塞证'。"""
        text = "【诊断】\n中医诊断：胸痹 — 痰浊壅塞证\n西医诊断：冠心病"
        sections = parse_sections(text)
        assert sections["中医疾病诊断"] == "胸痹"
        assert sections["中医证候诊断"] == "痰浊壅塞证"

    def test_double_em_dash(self):
        """双 em-dash '——' 也支持。"""
        text = "【诊断】\n中医诊断：感冒——风寒束表证"
        sections = parse_sections(text)
        assert sections["中医疾病诊断"] == "感冒"
        assert sections["中医证候诊断"] == "风寒束表证"

    def test_only_disease_no_syndrome(self):
        """只填疾病诊断，没填证候 → 只注册中医疾病诊断（让证候规则正确报缺）。"""
        text = "【诊断】\n中医诊断：感冒\n西医诊断：上感"
        sections = parse_sections(text)
        assert sections["中医疾病诊断"] == "感冒"
        assert "中医证候诊断" not in sections

    def test_placeholder_not_registered(self):
        """合并值是占位符时，两个虚拟章节都不注册。"""
        text = "【诊断】\n中医诊断：[未填写，需补充]\n西医诊断：感冒"
        sections = parse_sections(text)
        assert "中医疾病诊断" not in sections
        assert "中医证候诊断" not in sections

    def test_independent_section_not_overwritten(self):
        """老格式：医生手写独立的【中医证候诊断】章节，不被合并行覆盖。"""
        text = (
            "【中医证候诊断】\n肝阳上亢证（医生手写）\n"
            "【诊断】\n中医诊断：眩晕病（痰浊壅塞证）"
        )
        sections = parse_sections(text)
        # 独立章节优先
        assert sections["中医证候诊断"] == "肝阳上亢证（医生手写）"
        # 疾病诊断仍从合并行注册（独立章节没有【中医疾病诊断】）
        assert sections["中医疾病诊断"] == "眩晕病"

    def test_legacy_independent_tcm_diagnosis_section(self):
        """老格式：独立【中医诊断】章节里直接写合并值 → 也能拆解。"""
        text = "【中医诊断】\n感冒（风寒束表证）\n\n【西医诊断】\n上感"
        sections = parse_sections(text)
        assert sections["中医疾病诊断"] == "感冒"
        assert sections["中医证候诊断"] == "风寒束表证"

    def test_no_tcm_diagnosis_no_virtual(self):
        """病历里没"中医诊断"行 → 虚拟章节不注册。"""
        text = "【诊断】\n西医诊断：感冒"
        sections = parse_sections(text)
        assert "中医疾病诊断" not in sections
        assert "中医证候诊断" not in sections

    def test_split_helper_paren(self):
        assert _split_tcm_diagnosis("感冒（风寒束表证）") == ("感冒", "风寒束表证")

    def test_split_helper_dash(self):
        assert _split_tcm_diagnosis("胸痹 — 痰浊壅塞证") == ("胸痹", "痰浊壅塞证")

    def test_split_helper_single(self):
        assert _split_tcm_diagnosis("感冒") == ("感冒", "")

    def test_split_helper_empty(self):
        assert _split_tcm_diagnosis("") == ("", "")
