"""病历文本解析器（services/qc_engine/parser.py）

把病历正文按【XXX】章节解析成 Section 字典，**占位符在这一层就过滤干净**，
下游 checker / rubric 永远不再判定"是否未填写"——is_filled() 是唯一权威。

为什么单独抽出 parser 模块：
  旧 completeness_rules.parse_sections 既解析又判定，4 个阶段散落判断
  占位符 → 第一阶段忘了过滤导致 "5 个未填写还显示 100 分"。
  新设计治本：解析层只产 Section 对象，Section.is_filled() 决定是否已填——
  逻辑收编到 Section 类，永远只有一处判定。

解析三阶段：
  1. 普通章节：【XXX】标题 → 标题到下一个【 之间的文本
  2. 虚拟子行：【体格检查】内的"切诊·舌象：xxx"、【专项评估】内的
     "· 疼痛评估：xxx" → 注册成虚拟章节（"舌象"、"疼痛评估"）
  3. 中医诊断合并行：【诊断】内"中医诊断：感冒 — 风寒束表证" → 拆成
     "中医疾病诊断"、"中医证候诊断" 两个虚拟章节
"""
from __future__ import annotations

import re

from app.services.qc_engine.section import Section

# ── 虚拟子行映射（与 record_renderer 输出契约一致）────────────────────
# 父章节 → [(行前缀, 虚拟章节名), ...]
# LLM 输出的"切诊·舌象：xxx" 等子行被注册成顶层 Section，让 rubric 直接按
# §舌象 / §脉象 等名称访问。
_SECTION_LINE_PREFIXES: dict[str, list[tuple[str, str]]] = {
    "体格检查": [
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
    "诊断": [
        ("中医证候诊断：", "中医证候诊断"),
        ("中医疾病诊断：", "中医疾病诊断"),
        ("西医诊断：", "西医诊断"),
    ],
    "治疗意见及措施": [
        ("治则治法：", "治则治法"),
        ("处理意见：", "处理意见"),
        ("复诊建议：", "复诊建议"),
        ("注意事项：", "注意事项"),
    ],
}


def _norm_colon(s: str) -> str:
    """统一中英文冒号——LLM 输出可能混用 "：" / ":"。"""
    return s.replace(":", "：")


def _split_subsections(
    parent_content: str,
    prefixes: list[str],
) -> dict[str, str]:
    """按所有 prefix 切分父章节文本，返回 {prefix: 该 prefix 后到下一 prefix/末尾的内容}。

    设计要点：
      - 不依赖行首位置（LLM 可能把多个子行写在同一行：
        "望诊：xxx。闻诊：yyy。切诊·舌象：zzz"），用位置切分更稳
      - 自带冒号的 prefix（"切诊·舌象："）取一行值（避免吞下一段非 prefix 行）
      - 不带冒号的 prefix（"· 疼痛评估"）在 raw 内再找首个"：" 后取值
    """
    norm_content = _norm_colon(parent_content)
    occurrences: list[tuple[int, str]] = []
    for prefix in prefixes:
        norm_prefix = _norm_colon(prefix)
        start = 0
        while True:
            pos = norm_content.find(norm_prefix, start)
            if pos == -1:
                break
            occurrences.append((pos, prefix))
            start = pos + 1
    occurrences.sort(key=lambda x: x[0])

    result: dict[str, str] = {}
    for i, (pos, prefix) in enumerate(occurrences):
        value_start = pos + len(_norm_colon(prefix))
        value_end = occurrences[i + 1][0] if i + 1 < len(occurrences) else len(norm_content)
        raw = norm_content[value_start:value_end]
        if prefix.endswith("：") or prefix.endswith(":"):
            # 自带冒号 → 取首行避免吞下一段非 prefix 行
            head = raw.lstrip()
            nl = head.find("\n")
            value = (head[:nl] if nl != -1 else head).strip()
        else:
            # 不带冒号 → 在 raw 内再找首个"：" 后取值
            head, sep, tail = raw.partition("：")
            value = tail.strip() if sep else head.strip()
        value = value.rstrip(" 。.\n")
        if prefix not in result or not result[prefix]:
            result[prefix] = value
    return result


def _split_tcm_diagnosis(merged_value: str) -> tuple[str, str]:
    """把 LLM 合并写法 "感冒（风寒束表证）" / "感冒 — 风寒束表证" 拆成 (疾病, 证候)。

    支持格式（按优先级）：
      1. "X（Y）" / "X(Y)" — 中/英文括号
      2. "X — Y" / "X—Y" / "X – Y" — 各类破折号
      3. "X" — 单值，视作疾病诊断；证候空（让 §中医证候诊断 报缺）
    """
    s = merged_value.strip().rstrip(" 。.\n")
    if not s:
        return "", ""

    # 括号格式
    paren = re.match(r"^(.+?)\s*[（(]\s*(.+?)\s*[)）]\s*$", s)
    if paren:
        return paren.group(1).strip().rstrip(" 。."), paren.group(2).strip().rstrip(" 。.")

    # 破折号格式（半角"-"不切，避免疾病名带连字符歧义）
    for sep in ["——", "—", "–"]:
        if sep in s:
            parts = s.split(sep, 1)
            return parts[0].strip().rstrip(" 。."), parts[1].strip().rstrip(" 。.")

    # 单值
    return s, ""


def parse_record(text: str) -> dict[str, Section]:
    """把病历正文解析成 {章节名: Section} 字典。

    所有占位符 / 空值在这里通过 Section.is_filled() 隔离——下游 checker / rubric
    永远不再判定字符串"是否未填写"，统一调 section.is_filled()。

    Args:
        text: 病历正文（含【XXX】章节标题）

    Returns:
        dict[str, Section]: key 是章节名（含原章节 + 虚拟子行 + 拆分后的中医诊断）
                            value 是 Section 对象（is_filled 已就绪）

    使用约束：
        调用方禁止直接 if sections[name].raw_value——必须 section.is_filled()。
    """
    sections: dict[str, Section] = {}

    # 阶段 1：原章节解析
    pattern = re.compile(r"【([^】]+)】")
    matches = list(pattern.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        # 注意：这里**不过滤占位符**——交给 Section.is_filled() 判定
        # 把 raw_value 完整保留供 contains / 长度检查规则使用
        sections[name] = Section(name=name, raw_value=content)

    # 阶段 2：父章节内子行解析 → 虚拟章节
    for parent_name, line_configs in _SECTION_LINE_PREFIXES.items():
        parent = sections.get(parent_name)
        if parent is None or not parent.normalized:
            continue
        prefixes = [p for p, _ in line_configs]
        sub_values = _split_subsections(parent.raw_value, prefixes)
        for prefix, virtual_name in line_configs:
            value = sub_values.get(prefix, "")
            # 子行的 raw_value 直接给 Section——是否已填仍由 Section.is_filled 判
            # 注意 setdefault：不覆盖原章节（独立的【中医疾病诊断】优先）
            if value:
                sections.setdefault(virtual_name, Section(name=virtual_name, raw_value=value))

    # 阶段 3：中医诊断合并行拆解（兼容 LLM 输出多种格式）
    merged: str | None = None
    if "中医诊断" in sections and sections["中医诊断"].is_filled():
        merged = sections["中医诊断"].normalized.splitlines()[0].strip()
    elif "诊断" in sections and sections["诊断"].is_filled():
        m = re.search(r"中医诊断[：:]\s*([^\n]+)", sections["诊断"].normalized)
        if m:
            merged = m.group(1).strip()

    if merged:
        disease, syndrome = _split_tcm_diagnosis(merged)
        if disease:
            sections.setdefault("中医疾病诊断", Section(name="中医疾病诊断", raw_value=disease))
        if syndrome:
            sections.setdefault("中医证候诊断", Section(name="中医证候诊断", raw_value=syndrome))

    # 阶段 4：体格检查段内"舌脉合并描述"启发式（兼容 LLM 不按 prompt 契约写子行）
    # 例如末尾一句"舌红，苔薄黄，脉弦。" → 注册舌象 / 脉象虚拟章节
    exam = sections.get("体格检查")
    if exam and exam.is_filled():
        exam_text = exam.normalized
        if "舌象" not in sections:
            tongue_match = re.search(
                r"(舌[^，,。；;\n]{1,15}[，,；;]\s*(?:舌)?苔[^，,。；;\n]{1,15})",
                exam_text,
            )
            if tongue_match:
                v = tongue_match.group(1).strip().rstrip(" 。.")
                if v:
                    sections["舌象"] = Section(name="舌象", raw_value=v)
        if "脉象" not in sections:
            pulse_match = re.search(
                r"(脉(?:象[：:])?\s*"
                r"(?:[弦浮沉迟数滑涩虚实细弱洪紧缓芤革牢濡伏动促结代和平]"
                r"[^，,。；;\n]{0,8}))",
                exam_text,
            )
            if pulse_match:
                v = pulse_match.group(1).strip().rstrip(" 。.")
                if v:
                    sections["脉象"] = Section(name="脉象", raw_value=v)

    return sections


def get_section(sections: dict[str, Section], name: str) -> Section:
    """取章节，缺失时返回空 Section（避免调用方写 None 判断）。

    设计意图：让 checker 写法简洁——
        return get_section(ctx.sections, "现病史").is_filled() == False
    而不是：
        s = ctx.sections.get("现病史"); return not s or not s.is_filled()
    """
    return sections.get(name) or Section(name=name, raw_value="")
