"""评分器（services/qc_engine/scorer.py）

按 Rubric 计算分数 + 等级 + 扣分明细。

扣分模型（严格按浙江省评分标准 PDF）：
  1. 起始 100 分
  2. 遍历每个 RubricItem：
     a. 先检查 veto_rules（单项否决，仅住院）—— 触发即固定扣 10 分，
        该 item 不再检查 deduction_rules（PDF 备注 6"不累积扣分"）
     b. 未触发 veto → 遍历 deduction_rules，累加扣分
     c. 单项累积扣分不超过 item.max_points（**大项上限保护**）
  3. 总扣分 = sum(每项实际扣分)
  4. 最终分 = max(0, 100 - 总扣分)
  5. 等级按 rubric.grade_thresholds 判定

为什么是 100 起点扣分而非 0 起点加分：
  浙江省 PDF 全部按"扣分"语义编写（"未及时完成扣 5 分"），
  代码与 PDF 表述对齐方便审计、便于医生理解扣分明细。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.qc_engine.checker import RecordContext
from app.services.qc_engine.rubric import (
    VETO_DEDUCT_POINTS,
    DeductionRule,
    Rubric,
    RubricItem,
    VetoRule,
)


@dataclass(frozen=True)
class Deduction:
    """单条扣分记录——用于前端扣分明细表格显示。"""

    item_name: str          # 大项名（"现病史"）
    rule_code: str          # 规则唯一码（"OP-PRESENT-ILLNESS-01"）
    description: str        # 扣分理由（PDF 原文）
    points: float           # 实际扣分值
    is_veto: bool = False   # 是否单项否决


@dataclass(frozen=True)
class ItemScore:
    """单项得分明细——便于前端按 PDF 大项展示。"""

    name: str
    max_points: float
    deducted: float
    deductions: tuple[Deduction, ...]
    veto_triggered: bool = False

    @property
    def score(self) -> float:
        """该项实际得分 = max_points - 实际扣分（已应用上限保护）。"""
        return self.max_points - self.deducted


@dataclass(frozen=True)
class ScoreReport:
    """完整评分报告——qc_stream_service 返给前端的最终结果。"""

    rubric_name: str
    rubric_version: str
    score: float                      # 0-100
    grade: str                        # "合格" / "不合格" / "甲级" / "乙级" / "丙级"
    passed: bool                      # 是否达到合格阈值
    item_scores: tuple[ItemScore, ...]
    total_deducted: float
    deductions: tuple[Deduction, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        """序列化给 SSE / API 响应——按 PDF 四列表格结构。"""
        return {
            "rubric_name": self.rubric_name,
            "rubric_version": self.rubric_version,
            "score": round(self.score, 1),
            "grade": self.grade,
            "passed": self.passed,
            "total_deducted": round(self.total_deducted, 1),
            "items": [
                {
                    "name": it.name,
                    "max_points": it.max_points,
                    "score": round(it.score, 1),
                    "deducted": round(it.deducted, 1),
                    "veto_triggered": it.veto_triggered,
                    "deductions": [
                        {
                            "rule_code": d.rule_code,
                            "description": d.description,
                            "points": d.points,
                            "is_veto": d.is_veto,
                        }
                        for d in it.deductions
                    ],
                }
                for it in self.item_scores
            ],
        }


def _score_item(item: RubricItem, ctx: RecordContext) -> ItemScore:
    """计算单个评分大项的得分。

    步骤：
      1. 检查 veto_rules：任一触发 → 扣 10 分（不累积），返回
      2. 检查 deduction_rules：累加扣分
      3. 累积扣分上限 = item.max_points
    """
    deductions: list[Deduction] = []

    # 1. 单项否决（住院专属）
    for veto in item.veto_rules:
        if _safe_check(veto, ctx):
            deductions.append(Deduction(
                item_name=item.name,
                rule_code=veto.code,
                description=veto.description,
                points=VETO_DEDUCT_POINTS,
                is_veto=True,
            ))
            # PDF 备注 6："扣 10 分，不累积扣分"——此项不再走 deduction_rules
            actual_deducted = min(VETO_DEDUCT_POINTS, item.max_points)
            return ItemScore(
                name=item.name,
                max_points=item.max_points,
                deducted=actual_deducted,
                deductions=tuple(deductions),
                veto_triggered=True,
            )

    # 2. 普通扣分规则累加
    raw_deducted = 0.0
    for rule in item.deduction_rules:
        if _safe_check(rule, ctx):
            deductions.append(Deduction(
                item_name=item.name,
                rule_code=rule.code,
                description=rule.description,
                points=rule.deduct_points,
                is_veto=False,
            ))
            raw_deducted += rule.deduct_points

    # 3. 大项上限保护——单项扣分不超过该项 max_points
    actual_deducted = min(raw_deducted, item.max_points)
    return ItemScore(
        name=item.name,
        max_points=item.max_points,
        deducted=actual_deducted,
        deductions=tuple(deductions),
        veto_triggered=False,
    )


def _safe_check(rule: DeductionRule | VetoRule, ctx: RecordContext) -> bool:
    """安全调用规则 checker——任何异常视为"未触发扣分"。

    防御性：规则函数自己出 bug 不该让整个评分崩。日志由调用方决定要不要打。
    """
    try:
        return bool(rule.checker(ctx))
    except Exception:
        # 规则 bug 不阻断评分——单条规则崩溃只损失它一条的扣分判定
        # 这里用 pass 而非 logger.warning 保持 scorer 模块纯净；
        # 调用方（qc_stream_service）可以包一层 logger
        return False


def score(rubric: Rubric, ctx: RecordContext) -> ScoreReport:
    """评分主入口——按 Rubric 计算 ScoreReport。

    Args:
        rubric: 评分表（zj_outpatient_emergency_2023 等代码常量）
        ctx: 评分上下文（含病历正文解析后的 sections + 元数据）

    Returns:
        ScoreReport: 含分数、等级、每大项扣分明细
    """
    item_scores: list[ItemScore] = []
    all_deductions: list[Deduction] = []
    total_deducted = 0.0

    for item in rubric.items:
        item_score = _score_item(item, ctx)
        item_scores.append(item_score)
        all_deductions.extend(item_score.deductions)
        total_deducted += item_score.deducted

    final_score = max(0.0, 100.0 - total_deducted)
    return ScoreReport(
        rubric_name=rubric.name,
        rubric_version=rubric.version,
        score=final_score,
        grade=rubric.grade_for(final_score),
        passed=rubric.passed(final_score),
        item_scores=tuple(item_scores),
        total_deducted=total_deducted,
        deductions=tuple(all_deductions),
    )
