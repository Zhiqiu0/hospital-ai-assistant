"""Section 值对象与占位符常量（services/qc_engine/section.py）

L3 治本核心：把"什么算已填写"从散落 4 阶段的 if 判断，提升为类型层的单一权威。

设计原则：
  - Section.is_filled() 是全项目**唯一**的判定入口
  - 所有 checker / rubric 调它，禁止直接 `if sections[name]`
  - 占位符常量 PLACEHOLDERS 集中维护

这样新加规则不可能再"忘了过滤占位符"——规则只能通过 Section 接口拿数据。
"""
from __future__ import annotations

from dataclasses import dataclass

# ─── 占位符常量（与 record_schemas.PLACEHOLDER 保持同步） ───────────────
#
# 这些值视为"未填写"——即使 raw_value 非空字符串。
# record_renderer 在 LLM 输出字段缺失时统一渲染成 "[未填写，需补充]"，
# parser 必须识别这些占位符，否则 is_filled 会误判"已填写"导致评分虚高。
PLACEHOLDERS: frozenset[str] = frozenset({
    "[未填写，需补充]",
    "[未填写]",
    "未填写，需补充",
    "未填写",
    "（待填写）",
    "(待填写)",
    "暂未填写",
    "无",        # 边界：医生用"无"表示"否认"是合法的，但纯"无"歧义大
                 # 这里保留——is_filled 用 MIN_LEN 兜底，让"无"通过（长度=1 ≥ 1）
})

# 已填写的最小长度阈值。"否认"、"无"、"暂无"等医生短句合规，长度 ≥1 即通过；
# 过度严格会误伤医生简洁记录习惯。
MIN_FILLED_LENGTH = 1


@dataclass(frozen=True)
class Section:
    """病历章节的不可变值对象。

    Attributes:
        name: 章节名（如 "现病史"、"既往史"），用于规则匹配
        raw_value: 原始内容，可能含占位符 / 空白 / 真实内容

    使用约束（强制）：
        调用方判定"是否已填写"必须调 is_filled()，不可直接 if section.raw_value。
        理由：raw_value="[未填写，需补充]" 是非空字符串但语义上是未填写——
              旧实现的 4 阶段散落判定就是栽在这。
    """

    name: str
    raw_value: str

    @property
    def normalized(self) -> str:
        """去除首尾空白后的内容（不修剪行内换行）。"""
        return self.raw_value.strip()

    def is_filled(self) -> bool:
        """全项目唯一权威：判定该 Section 是否真有医生填写的内容。

        判定规则（按重要性排序）：
          1. 非空字符串
          2. 不在 PLACEHOLDERS 占位符集合内
          3. 去空白后长度 ≥ MIN_FILLED_LENGTH

        Returns:
            True  : 医生真的填了内容（即使是"否认"这种短答）
            False : 空 / 纯空白 / 占位符
        """
        v = self.normalized
        if not v:
            return False
        if v in PLACEHOLDERS:
            return False
        return len(v) >= MIN_FILLED_LENGTH

    def contains(self, keyword: str) -> bool:
        """raw_value 是否包含关键词（仅在 is_filled 时返回 True）。

        用于"现病史里必须含起病时间描述"这种带语义的检查规则。
        """
        if not self.is_filled():
            return False
        return keyword in self.normalized
