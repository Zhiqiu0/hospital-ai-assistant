"""
病历渲染共享组件（services/ai/_render_common.py）

record_renderer.py 拆分出的叶子模块：只放「被多个渲染器复用」的
底层 helper 与两个通用渲染器。本模块不 import record_renderer，
避免循环导入（依赖方向：record_renderer / _render_* → _render_common）。
"""

from __future__ import annotations

from typing import Optional

from app.services.ai.record_schemas import PLACEHOLDER, coalesce_field


# ─── 共享 helpers ───────────────────────────────────────────────────


def _v(data: dict, key: str, default: str = PLACEHOLDER) -> str:
    """从 data 取字段值，空值 / 非字符串兜底为 default（薄壳，复用 coalesce_field）。"""
    return coalesce_field(data.get(key), default)


def normalize_vitals_line(value: str) -> str:
    """生命体征行归一：非空且缺 "T:" 前缀时补 "T:[未测] "。

    契约要求体征行以 T: 起头（QC 解析器按行首 "T:" 识别【生命体征】子行），
    LLM 在急诊只测了 P/BP 时会输出 "P:92次/分 BP:128/78mmHg"——行首不是 T:
    → 质控看不见整行 → 误报"急诊无生命体征记录"（2026-08-20 第二轮走查实锤）。
    缺项写 [未测] 本就是真实性规则 4 的契约写法，这里做确定性兜底。
    """
    v = (value or "").strip()
    if not v or v.startswith("[") or v.startswith("T:"):
        return value
    return f"T:[未测] {v}"


def _section(header: str, body: str) -> str:
    """章节级拼装：'【XXX】\\n{body}'，body 已是规范化文本。"""
    return f"{header}\n{body}"


def _subline(prefix: str, value: str) -> str:
    """子行拼装：'{prefix}{value}'。prefix 自带冒号（如 '望诊：' / '· 疼痛评估：'）。

    值内换行压平（2026-08-28 极端字符审计）：LLM 偶发在行级字段值里带换行，
    渲染出"切诊·舌象：舌红/苔黄"两行后 QC 行级解析只认首行（静默截断）、
    前端撤销按单行还原会残留孤行。行级字段语义上就是单行，压平无信息损失。
    """
    flat = (str(value).replace("\r\n", " ").replace("\n", " ")
            .replace("\r", " ").replace("\t", " "))
    return f"{prefix}{flat}"

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


# ─── 通用"章节级整段"渲染器（病程类复用） ───────────────────────────


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
