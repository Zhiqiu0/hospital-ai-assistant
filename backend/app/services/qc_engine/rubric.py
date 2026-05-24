"""评分表核心数据结构（services/qc_engine/rubric.py）

按浙江省卫健委评分标准 PDF 设计的不可变数据类型：
  PDF 一行检查项                   → DeductionRule
  PDF 一行单项否决项（仅住院）     → VetoRule
  PDF 一个大项（带分值）           → RubricItem
  PDF 整张评分表                   → Rubric

为什么是代码常量而非 DB 表：
  浙江省评分标准是国家法定标准，admin 不该有改的能力。
  PR review 是改它的唯一通道（合规留痕 + 不可被运营误改）。

为什么 frozen=True：
  评分规则是只读引用——any mutation would be a bug。
  类型层把它锁死，避免运行时被业务代码乱改。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

# checker 函数签名：接收 RecordContext，返回 True 表示触发扣分。
# 用 forward ref 避免循环导入（RecordContext 定义在 checker.py）。
CheckerFn = Callable[["RecordContext"], bool]  # noqa: F821

# 评分对象的范围：
#   single   = 单份病历（门、急诊场景）
#   encounter = 整个接诊综合（住院场景，多文档拼装）
RecordScope = Literal["single", "encounter"]


@dataclass(frozen=True)
class DeductionRule:
    """一条扣分细则——对应 PDF '评分说明' 列的一行。

    示例（PDF 门急诊"现病史 20 分"项下的一条）：
        DeductionRule(
            code="OP-PRESENT-ILLNESS-01",
            description="主要症状、体征描述不清",
            deduct_points=5,
            checker=lambda ctx: not ctx.section("现病史").contains("起病"),
        )

    Attributes:
        code: 唯一码（前缀区分门诊/住院：OP-* / IP-*），便于测试 fixture 和审计
        description: PDF 原文（用户看到的扣分理由）
        deduct_points: PDF 上的扣分值（浙江省标准都是整数或 0.5 的倍数）
        checker: (RecordContext) -> bool，True 触发扣分
        target_field: 该规则违反时，AI 修复应写入哪个具体业务字段。
            治本动机（2026-05-19）：原 issue 的 field_name 用大项名（如"治疗意见
            及措施"），但病历模板里这是个合并章节，下面是 4 个子行；前端按大项名
            找不到对应章节，只能把修复文本追加到病历末尾。
            标注子字段后，前端就知道按"治则治法："/"处理意见："等行前缀精准替换。
            字段名约定用前端 FIELD_TO_LINE_PREFIX / FIELD_TO_SECTION 的中文键。
            None → 前端走大项名兜底（适用大项与单字段 1:1 映射的场景，如"主诉"）。
    """

    code: str
    description: str
    deduct_points: float
    checker: CheckerFn
    target_field: str | None = None


# 单项否决固定扣分（PDF 住院 2021 版备注 6 明确："单项否决指标计分时扣 10 分，不累积扣分"）
VETO_DEDUCT_POINTS: float = 10.0


@dataclass(frozen=True)
class VetoRule:
    """单项否决规则（仅住院评分标准适用）。

    PDF 备注 6：触发后扣 10 分，**同一大项内不再累积**其他扣分。
    例：主要诊断填写或编码错误 → 触发即扣 10 分，该大项不再扣其他细则。

    门诊评分标准没有"单项否决"概念，门诊 Rubric 的 veto_rules 应保持空 tuple。

    Attributes:
        code: 唯一码（前缀 IP-VETO-*）
        description: PDF 原文（如"主要诊断填写或编码错误"）
        checker: (RecordContext) -> bool
        target_field: 跟 DeductionRule.target_field 同义——标识该 veto 违反时
            AI 修复应写入哪个具体业务字段。同样走 _writable_fields 白名单校验。
            None → 前端走大项名兜底（不推荐，veto 应明确指向修复目标）。
    """

    code: str
    description: str
    checker: CheckerFn
    target_field: str | None = None


@dataclass(frozen=True)
class RubricItem:
    """评分大项——对应 PDF 一行（含分值）。

    例：PDF 门急诊"现病史 20 分" → RubricItem(name="现病史", max_points=20, ...)

    Attributes:
        name: 大项名（用于扣分明细显示，与 PDF 文字一致）
        max_points: 该项满分（同时是扣分上限——单项扣分不超过 max_points）
        description: PDF "检查要求" 列文字（用户审查时能对照）
        deduction_rules: 该项下所有扣分细则
        veto_rules: 该项下所有单项否决规则（门诊为空 tuple）
    """

    name: str
    max_points: float
    description: str
    deduction_rules: tuple[DeductionRule, ...]
    veto_rules: tuple[VetoRule, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class GradeThreshold:
    """等级阈值定义。

    门诊 PDF 注 5："90 分以下判定为不合格病历"——只分合格/不合格。
    住院 PDF 备注 8："90 分以下为乙级病历，80 分以下为丙级病历"——三级。

    Attributes:
        min_score: 该等级的最低分（含）
        label: 等级标签（"合格" / "甲级" / "乙级" / "丙级"）
    """

    min_score: float
    label: str


@dataclass(frozen=True)
class Rubric:
    """完整评分表——对应一份完整 PDF。

    一份 Rubric 是 PR review 才能改的代码常量（不在 admin 后台编辑）。
    版本号用 PDF 发布版本（如门急诊 2023、住院 2021），标准升级走代码 PR。

    Attributes:
        name: 标准全名（"浙江省中医门、急诊病历评分标准"）
        version: PDF 版本标识（"2023" / "2021"）
        record_scope: 评分对象的范围（single / encounter）
        items: 全部评分大项
        grade_thresholds: 等级阈值列表，按 min_score 降序排列
                          评分时从高到低匹配，第一个 score ≥ min_score 的等级即为结果

    举例：
        门诊 Rubric.grade_thresholds = (
            GradeThreshold(90, "合格"),
            GradeThreshold(0, "不合格"),
        )
        住院 Rubric.grade_thresholds = (
            GradeThreshold(90, "甲级"),
            GradeThreshold(80, "乙级"),
            GradeThreshold(0, "丙级"),
        )
    """

    name: str
    version: str
    record_scope: RecordScope
    items: tuple[RubricItem, ...]
    grade_thresholds: tuple[GradeThreshold, ...]

    def __post_init__(self) -> None:
        """构造时不变量检查——防加 Rubric 出错。"""
        # 等级阈值必须按 min_score 降序（评分匹配靠这个顺序）
        scores = [t.min_score for t in self.grade_thresholds]
        if scores != sorted(scores, reverse=True):
            raise ValueError(
                f"Rubric {self.name}: grade_thresholds 必须按 min_score 降序排列"
            )
        # 最低等级 min_score 必须是 0（兜底所有分数）
        if self.grade_thresholds and self.grade_thresholds[-1].min_score != 0:
            raise ValueError(
                f"Rubric {self.name}: 最低等级的 min_score 必须为 0（兜底所有分数）"
            )
        # 单项否决仅住院适用——门诊 Rubric 的 veto_rules 必须为空
        if self.record_scope == "single":
            for item in self.items:
                if item.veto_rules:
                    raise ValueError(
                        f"Rubric {self.name}: 单文档评分（门诊）不允许 veto_rules，"
                        f"违规项：{item.name}"
                    )

        # L2 契约（2026-05-19）：每条 DeductionRule / VetoRule 的 target_field 要么 None，
        # 要么命中 _writable_fields.ALL_KNOWN_TARGET_FIELDS 白名单——避免后端规则改完
        # 忘了同步前端映射，让"修复文本默默写错位置"这类反复出现的 bug 在 module import 时就报错。
        # 延迟 import 避免循环依赖（rubric.py 是 _writable_fields.py 上游基础组件）
        from app.services.qc_engine._writable_fields import ALL_KNOWN_TARGET_FIELDS
        for item in self.items:
            for rule in item.deduction_rules:
                if rule.target_field is not None and rule.target_field not in ALL_KNOWN_TARGET_FIELDS:
                    raise ValueError(
                        f"Rubric {self.name}: rule {rule.code} 的 target_field="
                        f"{rule.target_field!r} 未在 _writable_fields.py 白名单注册——"
                        f"添加新字段需同步前端 qcFieldMaps.ts 的映射 + NON_WRITABLE_FIELDS"
                    )
            for veto in item.veto_rules:
                if veto.target_field is not None and veto.target_field not in ALL_KNOWN_TARGET_FIELDS:
                    raise ValueError(
                        f"Rubric {self.name}: veto {veto.code} 的 target_field="
                        f"{veto.target_field!r} 未在 _writable_fields.py 白名单注册"
                    )

    @property
    def total_points(self) -> float:
        """各大项分值之和——浙江省 PDF 总分都是 100。"""
        return sum(item.max_points for item in self.items)

    def grade_for(self, score: float) -> str:
        """按等级阈值表判定分数对应的等级标签。"""
        for threshold in self.grade_thresholds:
            if score >= threshold.min_score:
                return threshold.label
        # __post_init__ 保证最低 min_score=0，理论不会到这里
        return self.grade_thresholds[-1].label

    def passed(self, score: float) -> bool:
        """是否合格——以最高等级阈值为合格线。

        门诊：≥90 合格
        住院：≥90 甲级即合格（业内通用：甲级 = 合格，乙级 = 待整改，丙级 = 不合格，
              但 PDF 备注 8 只定义了等级，没明说哪级算合格——按最高阈值兜底）
        """
        if not self.grade_thresholds:
            return False
        return score >= self.grade_thresholds[0].min_score
