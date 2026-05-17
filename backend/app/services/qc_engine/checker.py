"""病历检查器（services/qc_engine/checker.py）

提供 RecordContext（评分上下文）+ check_record 主入口，对接 rubric。

RecordContext 抽象了"评分对象"——
  - single 范围：单份病历文本 + 元数据
  - encounter 范围：整个接诊的多文档（住院场景，下一期实现）

为什么把 ctx 抽出来：
  DeductionRule.checker 签名是 (RecordContext) -> bool，让规则统一接口。
  这样住院 rubric 改成跨文档评分时，单文档规则代码完全不变——
  只是 RecordContext 内部多了 admission_note / course_records 等字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.services.qc_engine.parser import get_section, parse_record
from app.services.qc_engine.section import Section


@dataclass(frozen=True)
class RecordContext:
    """评分上下文——传给所有 DeductionRule.checker / VetoRule.checker。

    门、急诊场景（record_scope="single"）：
      - sections：从 record_text 解析出来的章节字典
      - patient_gender / is_first_visit / is_emergency / record_type：元数据
      - inquiry：医生录入的问诊字段字典（双源校验时备用）

    住院场景（record_scope="encounter"，下一期实现）：
      - 多个 sections（按 record_type 分桶）
      - 跨文档聚合字段
    """

    record_text: str
    sections: dict[str, Section]
    record_type: str = "outpatient"
    is_emergency: bool = False
    is_first_visit: bool = True
    patient_gender: str = ""
    inquiry: dict[str, str] = field(default_factory=dict)

    def section(self, name: str) -> Section:
        """取章节——缺失时返回空 Section，避免规则代码写 None 判断。

        用法：
            ctx.section("现病史").is_filled()
            ctx.section("现病史").contains("起病")
        """
        return get_section(self.sections, name)

    def any_section_filled(self, *names: str) -> bool:
        """任一章节已填即返回 True。

        用于"中医诊断（疾病或证候至少有一个）"这种 OR 规则。
        """
        return any(self.section(name).is_filled() for name in names)

    def text_contains(self, keyword: str) -> bool:
        """病历原文是否包含关键词（无视章节）。

        用于"是否提及急救药品"这种跨章节关键词检查。
        """
        return keyword in self.record_text

    def inquiry_field_filled(self, field_name: str) -> bool:
        """inquiry 字典里指定字段是否非空且非占位符。

        双源校验：当病历文本解析判定缺失，但 inquiry 字段实际有值时，认作已填。
        前端 QC 请求会带 inquiry 字段，给规则引擎作交叉验证用。
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
    is_emergency: bool = False,
    is_first_visit: bool = True,
    patient_gender: str = "",
    inquiry: Optional[dict[str, str]] = None,
) -> RecordContext:
    """从病历正文 + 元数据构造 RecordContext。

    路由层调这个入口，不直接 new RecordContext——这样未来给 ctx 加新字段
    （比如住院的 multi-doc）时只改这一处。
    """
    return RecordContext(
        record_text=record_text,
        sections=parse_record(record_text),
        record_type=record_type,
        is_emergency=is_emergency or record_type == "emergency",
        is_first_visit=is_first_visit,
        patient_gender=patient_gender or "",
        inquiry=inquiry or {},
    )
