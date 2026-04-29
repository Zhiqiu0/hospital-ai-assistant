"""
完整性质控规则引擎（DB 驱动）

规则数据从 qc_rules 表动态加载（rule_type='completeness'）。

匹配逻辑（两层，优先级依次降低）：
  1. 章节名匹配（section_names）：把病历按【XXX】解析成章节 Map，
     检查章节是否存在且有非空内容。与格式完全无关，最健壮。
  2. 关键词兜底（keywords）：在原始文本里做字符串包含检查，
     用于无法用章节名表达的规则（如生命体征、住院评估等）。

规则定义时：
  - 能用章节名的优先写 section_names（存在 keywords 字段中，以 "§" 前缀区分）
  - 其余情况用 keywords 做文本匹配

scope 过滤：
  - all      → 始终执行
  - inpatient → is_inpatient=True 时才执行
  - revisit  → is_first_visit=False 时才执行
  - tcm      → 病历含中医章节时才执行
"""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.config import QCRule

logger = logging.getLogger(__name__)

# 章节前缀标记：keywords 中以此开头的条目视为章节名，走章节解析逻辑
_SECTION_PREFIX = "§"

# 中医相关章节名，用于判断病历是否含中医内容
_TCM_SECTION_NAMES = {"中医诊断", "中医证候诊断", "中医疾病诊断", "舌象", "脉象", "中医四诊"}

# ─── 章节内子行 → 虚拟章节映射（与前端 FIELD_TO_LINE_PREFIX 契约一致）─────
#
# Audit Round 4 引入：LLM 一键生成时，部分字段不是独立章节，而是章节内的一行
# （如【体格检查】下的"切诊·舌象：xxx"、【专项评估】下的"· 疼痛评估（NRS评分）：xxx"）。
# 但 QC 规则的 keywords 仍写的是 §舌象 / §脉象 / §疼痛评估 等独立章节名。
# 如果不做子行解析，规则永远找不到这些字段 → 即使医生填写了内容也报"未填写"（用户痛点）。
#
# 修复：parse_sections 解析完原章节后，扫描"父章节内文本"，
# 识别匹配前缀的行，提取行内容（占位符忽略），注册成虚拟章节供 § 规则匹配。
#
# 与 frontend/src/components/workbench/qcFieldMaps.ts → FIELD_TO_LINE_PREFIX 必须一致。
# 后端 test_prompt_contract.py 反向断言 prompt 字符串里包含这些前缀。
_SECTION_LINE_PREFIXES: dict[str, list[tuple[str, str]]] = {
    # 父章节名 → [(行前缀, 虚拟章节名), ...]
    "体格检查": [
        # 生命体征行：以"T:"开头（按 prompt 契约必须为体格检查段第一行）。
        # 注册成虚拟章节"生命体征"供 §生命体征 规则匹配；同时让前端 QC 修复
        # "已写入"按钮走行级替换，避免章节级整段替换冲掉同段中医四诊行（用户报告 bug）。
        ("T:", "生命体征"),
        ("望诊：", "望诊"),
        ("闻诊：", "闻诊"),
        ("切诊·舌象：", "舌象"),
        ("切诊·脉象：", "脉象"),
    ],
    "专项评估": [
        ("· 疼痛评估", "疼痛评估"),
        ("· VTE风险", "VTE风险评估"),
        ("· 营养风险", "营养评估"),
        ("· 心理状态", "心理评估"),
        ("· 康复需求", "康复评估"),
        ("· 当前用药", "当前用药"),
        ("· 宗教信仰", "宗教信仰"),
    ],
    # 【诊断】段：兼容 LLM 输出多种格式
    #   合并行格式：    "中医诊断：项痹病 — 气滞血瘀证"           → 第三阶段拆解
    #   显式独立格式：  "中医疾病诊断：项痹病" + "中医证候诊断：气滞血瘀证"
    #                                                       → 第二阶段（本表）识别
    #   半显式格式：    "中医诊断：项痹病" + "中医证候诊断：气滞血瘀证"
    #                                                       → 本表识别 §中医证候诊断；
    #                                                         第三阶段从"中医诊断：xxx"拆 disease
    # 三种格式 QC 都能正确识别，避免"医生明明填了证候诊断却报未填"的误报。
    "诊断": [
        ("中医证候诊断：", "中医证候诊断"),
        ("中医疾病诊断：", "中医疾病诊断"),
        ("西医诊断：", "西医诊断"),
    ],
}

# 占位符 —— 这些值视为"未填写"（即使匹配到前缀，也不视作章节有内容）
_PLACEHOLDER_VALUES = {
    "[未填写，需补充]",
    "[未填写]",
    "未填写，需补充",
    "未填写",
    "（待填写）",
    "(待填写)",
    "暂未填写",
}


def _split_subsections(parent_content: str, prefixes: list[str]) -> dict[str, str]:
    """按所有 prefix 切分父章节文本，返回 {prefix: 该 prefix 之后到下一个 prefix/末尾的内容}。

    关键设计：**不依赖行首**——LLM 实际输出可能把多个子行写在同一行
    （"望诊：xxx。闻诊：xxx。切诊·舌象：xxx。切诊·脉象：xxx。"），按行首
    匹配会识别失败导致 QC 误报。

    切分逻辑：
      1. 在归一化后（中英文冒号统一）的父章节文本里找每个 prefix 的所有出现位置
      2. 按位置排序，每个 prefix 后到下一个 prefix（或文本末）之间是它的值
      3. 值修剪：去除前导冒号、空白；去除尾部句号 / 句末标点

    冒号兼容：prefix 里的中文"："和文本里的英文":"会归一化后再匹配。

    返回 dict 的 key 是**原始 prefix**（含"："），value 是修剪后的实际内容。
    """
    def _norm(s: str) -> str:
        return s.replace(":", "：")

    norm_content = _norm(parent_content)
    # 收集所有 prefix 的出现位置
    occurrences: list[tuple[int, str]] = []
    for prefix in prefixes:
        norm_prefix = _norm(prefix)
        start = 0
        while True:
            pos = norm_content.find(norm_prefix, start)
            if pos == -1:
                break
            occurrences.append((pos, prefix))
            start = pos + 1
    occurrences.sort(key=lambda x: x[0])

    # 切分：每个 prefix 后到下一个 prefix 之前
    #
    # 取值规则统一（按 prefix 是否自带冒号分流）：
    #   - prefix 以"：" / ":" 结尾（自带分隔符，如"切诊·舌象："、"T:"）→
    #     raw 整段是值。
    #     这样生命体征行"T:36.5℃ P:78次/分 R:18次/分 BP:120/80mmHg"
    #     不会被内部"P:"误切成"78次/分..."（2026-04-29 修）。
    #   - prefix 不带冒号（如"· 疼痛评估"、"· 宗教信仰"）→
    #     在 raw 里找首个"："之后的内容当值，
    #     兼容"· 宗教信仰" + "/饮食禁忌：无" 取"无"、
    #          "· 疼痛评估" + "（NRS评分）：3分" 取"3分"。
    result: dict[str, str] = {}
    for i, (pos, prefix) in enumerate(occurrences):
        value_start = pos + len(_norm(prefix))
        value_end = occurrences[i + 1][0] if i + 1 < len(occurrences) else len(norm_content)
        raw = norm_content[value_start:value_end]
        if prefix.endswith("：") or prefix.endswith(":"):
            # 前缀自带分隔符，value 取 raw 第一行
            # ⚠️ 不能取整段：下一个 prefix 之前可能夹着非 prefix 行（如"其余阳性体征：xxx"），
            # 取整段会把它吞进 value（2026-04-29 渲染器测试暴露的回归）。
            # LLM 按 prompt 契约每个子行写单行，取一行足够。
            head = raw.lstrip()
            nl = head.find("\n")
            value = (head[:nl] if nl != -1 else head).strip()
        else:
            # 前缀不带冒号，需要在 raw 里再找一个分隔冒号
            head, sep, tail = raw.partition("：")
            value = tail.strip() if sep else head.strip()
        # 去除句末标点 / 多余换行
        value = value.rstrip(" 。.\n")
        # 一个 prefix 理论上不会匹配多次；防御性保留首个有效值
        if prefix not in result or not result[prefix]:
            result[prefix] = value
    return result


def _split_tcm_diagnosis(merged_value: str) -> tuple[str, str]:
    """把 LLM 合并写法 "疾病名（证候名）" / "疾病名 — 证候名" 等拆成 (疾病, 证候)。

    背景：tcm_disease_diagnosis 和 tcm_syndrome_diagnosis 在 DB / 表单里是两个独立字段，
    但 prompts_generation.py 让 LLM 把它们合并成一行 "中医诊断：X（Y）" 写入【诊断】章节。
    QC 规则若按"独立章节"找 §中医证候诊断 永远找不到 → 误报"未填写"（用户痛点）。

    支持的合并格式（按优先级）：
      1. "X（Y）" / "X(Y)" — 中/英文括号（用户截图实际格式）
      2. "X — Y" / "X—Y" / "X – Y" — 各类破折号（prompt 推荐格式）
      3. "X" — 单值，全部视作疾病诊断；证候诊断空（让 §中医证候诊断 规则正确报缺）

    返回 (disease, syndrome)，任一为空字符串表示该项缺失。
    占位符值（"[未填写，需补充]"等）由调用方过滤，本函数不处理。
    """
    s = merged_value.strip().rstrip(" 。.\n")
    if not s:
        return "", ""

    # 1) 括号格式：X（Y）或 X(Y) — 取最后一对括号，避免疾病名内含括号歧义
    paren = re.match(r'^(.+?)\s*[（(]\s*(.+?)\s*[)）]\s*$', s)
    if paren:
        disease = paren.group(1).strip().rstrip(" 。.")
        syndrome = paren.group(2).strip().rstrip(" 。.")
        return disease, syndrome

    # 2) 破折号格式：em-dash / en-dash / 双连字符（半角"-"不切，避免疾病名带连字符歧义）
    for sep in ["——", "—", "–"]:
        if sep in s:
            parts = s.split(sep, 1)
            disease = parts[0].strip().rstrip(" 。.")
            syndrome = parts[1].strip().rstrip(" 。.")
            return disease, syndrome

    # 3) 单值：当作疾病诊断，证候缺失（保守）
    return s, ""


# 中医诊疗行为关键词，作为补充判断（章节名优先）
_TCM_ACTION_KEYWORDS = [
    "中药", "针灸", "推拿", "中医治疗", "辨证", "中药汤剂", "中成药",
    "穴位", "艾灸", "拔罐", "刮痧", "草药", "治则治法",
]


def parse_sections(text: str) -> dict[str, str]:
    """
    把病历全文按【章节名】解析为 {章节名: 内容} 的字典。

    三阶段解析：
      1. 普通章节：【XXX】 标题 → 标题到下一个【 之间的文本
      2. 虚拟章节：扫描【体格检查】/【专项评估】等父章节内的 prefix 子行
         （如 "切诊·舌象：xxx"、"· 疼痛评估：xxx"），注册成虚拟章节供
         规则引擎用 §舌象 / §疼痛评估 等关键词命中。
      3. 中医诊断合并行拆解：LLM 把"中医疾病诊断 + 中医证候诊断"合并写成
         "中医诊断：感冒（风寒束表证）" 或 "中医诊断：感冒 — 风寒束表证"
         位于【诊断】或【中医诊断】章节内，需要拆成两个虚拟章节让 QC 规则识别。

    虚拟章节解析忽略占位符（"[未填写，需补充]"等）—— 占位符视作未填写。

    与前端 FIELD_TO_LINE_PREFIX 契约一致；任一方修改都需同步对方 + 跑契约测试。
    """
    sections: dict[str, str] = {}

    # 第一阶段：原有章节解析
    pattern = re.compile(r'【([^】]+)】')
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections[name] = content

    # 第二阶段：父章节内子行解析 → 虚拟章节
    for parent_name, line_configs in _SECTION_LINE_PREFIXES.items():
        parent_content = sections.get(parent_name)
        if not parent_content:
            continue
        prefixes = [p for p, _ in line_configs]
        sub_values = _split_subsections(parent_content, prefixes)
        for prefix, virtual_name in line_configs:
            value = sub_values.get(prefix, "")
            # 占位符 / 空值视作未填写，不注册虚拟章节
            if value and value not in _PLACEHOLDER_VALUES:
                sections[virtual_name] = value

    # 第三阶段：拆"中医诊断"合并行 → 虚拟章节 中医疾病诊断 + 中医证候诊断
    #
    # 候选位置（按优先级）：
    #   a) 独立【中医诊断】章节 — 老格式，整段视作合并值
    #   b) 【诊断】章节里的 "中医诊断：xxx" 行 — 当前 prompt 走这条路
    #
    # 已存在独立的 §中医疾病诊断 / §中医证候诊断 章节时不覆盖（医生手填优先）。
    merged: str | None = None
    if "中医诊断" in sections and sections["中医诊断"]:
        merged = sections["中医诊断"].splitlines()[0].strip()
    elif "诊断" in sections and sections["诊断"]:
        m = re.search(r'中医诊断[：:]\s*([^\n]+)', sections["诊断"])
        if m:
            merged = m.group(1).strip()

    if merged and merged not in _PLACEHOLDER_VALUES:
        disease, syndrome = _split_tcm_diagnosis(merged)
        # 占位符 / 空值过滤；已有独立章节不覆盖
        if disease and disease not in _PLACEHOLDER_VALUES:
            sections.setdefault("中医疾病诊断", disease)
        if syndrome and syndrome not in _PLACEHOLDER_VALUES:
            sections.setdefault("中医证候诊断", syndrome)

    # 第四阶段：体格检查段内"舌脉合并描述"启发式识别（2026-04-30）
    #
    # 兼容场景：LLM 不按 prompt 契约写独立的"切诊·舌象：xxx"/"切诊·脉象：xxx"
    # 子行，而是把舌脉合并塞进体格检查段尾（如末尾一句"舌红，苔薄黄，脉弦。"）。
    # 第二阶段子行解析按 prefix 匹配找不到 → 舌象/脉象虚拟章节缺失 → QC 误报"未填写"。
    # 跟"中医诊断合并行"同类问题（用户多次反馈反复出现），启发式 fallback 识别。
    #
    # 匹配规则（仅在前面阶段未注册虚拟章节时生效，医生手填 / prompt 规范输出优先）：
    #   舌象：必须"舌X"+"苔Y"共现，避免误命中"舌咽神经"等病名
    #   脉象：必须"脉"后接经典脉名锚点（弦/浮/沉/数/滑/涩等），避免命中"脉搏88次/分"
    exam_content = sections.get("体格检查", "")
    if exam_content:
        if "舌象" not in sections:
            tongue_match = re.search(
                r"(舌[^，,。；;\n]{1,15}[，,；;]\s*(?:舌)?苔[^，,。；;\n]{1,15})",
                exam_content,
            )
            if tongue_match:
                value = tongue_match.group(1).strip().rstrip(" 。.")
                if value and value not in _PLACEHOLDER_VALUES:
                    sections["舌象"] = value
        if "脉象" not in sections:
            # 经典 28 脉锚点：避开"脉搏/脉率"等生命体征用语，要求紧跟脉名字
            pulse_match = re.search(
                r"(脉(?:象[：:])?\s*"
                r"(?:[弦浮沉迟数滑涩虚实细弱洪紧缓芤革牢濡伏动促结代和平]"
                r"[^，,。；;\n]{0,8}))",
                exam_content,
            )
            if pulse_match:
                value = pulse_match.group(1).strip().rstrip(" 。.")
                if value and value not in _PLACEHOLDER_VALUES:
                    sections["脉象"] = value

    return sections


def _is_tcm_record(text: str, sections: dict[str, str]) -> bool:
    """判断病历是否含中医内容：优先检查章节名，其次检查诊疗行为关键词。"""
    if any(name in sections for name in _TCM_SECTION_NAMES):
        return True
    return any(kw in text for kw in _TCM_ACTION_KEYWORDS)


def _check_rule(rule: QCRule, text: str, sections: dict[str, str]) -> bool:
    """
    检查单条规则是否命中（即内容是否存在）。
    返回 True 表示找到，False 表示缺失（触发问题）。

    keywords 中：
      - 以 § 开头的条目 → 章节名匹配（章节存在且有内容）
      - 其余条目       → 原始文本包含检查
    任意一项命中即视为存在。
    """
    keywords = rule.keywords or []
    if not keywords:
        return True  # 无关键词的规则不触发

    for kw in keywords:
        if kw.startswith(_SECTION_PREFIX):
            # §章节名 → 章节解析
            section_name = kw[len(_SECTION_PREFIX):]
            if section_name in sections and sections[section_name]:
                return True
        elif kw.startswith('【') and kw.endswith('】'):
            # 【章节名】 → 自动识别为章节解析（向后兼容旧格式）
            section_name = kw[1:-1]
            if section_name in sections and sections[section_name]:
                return True
        else:
            # 原始文本包含匹配（兜底，用于生命体征等无章节名的规则）
            if kw in text:
                return True
    return False


def _check_inquiry_field(field_name: str, inquiry: dict | None) -> bool:
    """B-lite 双源校验（2026-04-30）：检查 inquiry 字典里指定字段是否有非占位内容。

    用途：文本解析判定字段缺失（_check_rule 返回 False）时，再用 inquiry 字典
    交叉验证。前端调 QC 时本来就把表单字段全传过来（QuickQCRequest），这些字段
    是结构化的、不会"格式漂移"。两边都说缺才报问题，避免 LLM 输出格式漂移
    （如把"切诊·舌象：xxx"合并成"舌红，苔薄黄"）导致的误报。

    字段名约定：
      rule.field_name 与 QuickQCRequest 字段名一致（英文 key，如 chief_complaint /
      tongue_coating）。规则用中文 field_name 时此函数返回 False，回退到原行为
      （只看文本），不破坏既有规则。

    返回 True 表示 inquiry 里该字段有内容（应抑制规则触发）。
    """
    if not field_name or not inquiry:
        return False
    val = inquiry.get(field_name)
    if not isinstance(val, str):
        return False
    val = val.strip()
    if not val or val in _PLACEHOLDER_VALUES:
        return False
    return True


def _make_issue(rule: QCRule) -> dict:
    """将 QCRule ORM 对象转换为质控问题字典。"""
    return {
        "source": "rule",
        "issue_type": "completeness",
        "risk_level": rule.risk_level,
        "field_name": rule.field_name or "",
        "issue_description": rule.issue_description or rule.name,
        "suggestion": rule.suggestion or "",
        "score_impact": rule.score_impact or "",
    }


async def check_completeness(
    record_text: str,
    db: AsyncSession,
    is_inpatient: bool = False,
    is_first_visit: bool = True,
    patient_gender: str = "",
    inquiry: dict | None = None,
) -> list:
    """
    规则引擎：对病历文本做结构性完整性检查。

    - 优先用章节解析（§前缀）确定字段是否存在，与格式无关
    - 无章节名的规则退化为关键词文本匹配
    - 所有 issue 带 source='rule'，用于确定性评分门槛

    inquiry 双源校验（B-lite，2026-04-30）：
      文本解析判定缺失后，若 inquiry 字典里对应字段（按 rule.field_name 查）
      有非占位内容，则抑制本条规则。inquiry 来自前端表单/语音整理/LLM 一键
      生成产物（QuickQCRequest 自带这些字段），结构化数据不会有"格式漂移"，
      用它做交叉验证可消除 LLM 文本格式不规范导致的误报。
      inquiry 为 None 时退化为纯文本判定，与历史行为一致。
    """
    text = record_text or ""
    issues: list = []

    # 一次性解析章节，供所有规则复用
    sections = parse_sections(text)

    # 加载所有激活的完整性规则（Redis 缓存 60s，admin 写时主动失效）
    try:
        from app.services.qc_rules_cache import get_active_qc_rules
        rules = await get_active_qc_rules(db, "completeness")
    except Exception as exc:
        logger.error("rules.completeness: load_failed err=%s", exc)
        return []

    is_tcm = _is_tcm_record(text, sections)

    for rule in rules:
        scope = rule.scope or "all"
        gender_scope = getattr(rule, "gender_scope", "all") or "all"

        # scope 过滤
        if scope == "inpatient" and not is_inpatient:
            continue
        if scope == "revisit" and is_first_visit:
            continue
        if scope == "tcm" and not is_tcm:
            continue

        # 性别过滤：未知性别或性别不匹配时跳过限定规则
        if gender_scope != "all" and (not patient_gender or gender_scope != patient_gender):
            continue

        if not _check_rule(rule, text, sections):
            # B-lite 双源校验：文本没找到，但 inquiry 字段有内容 → 抑制误报
            if _check_inquiry_field(rule.field_name, inquiry):
                logger.debug(
                    "qc.completeness: suppressed by inquiry field=%s rule=%s",
                    rule.field_name, rule.name,
                )
                continue
            issues.append(_make_issue(rule))

    return issues
