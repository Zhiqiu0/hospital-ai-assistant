"""
AI 质控——评分表选择与扣分映射（services/ai/_qc_rubric.py）

从 qc_stream_service.py 拆出的纯逻辑（不碰 DB / SSE / LLM）：
  - _INPATIENT_RECORD_TYPES ：住院系列 record_type 白名单
  - _select_rubric          ：按 record_type 路由到法定评分表
  - _deductions_to_issues   ：ScoreReport 扣分列表 → 前端 qcIssues 结构

拆分目的：把评分表路由与结构转换从服务门面剥离，主文件专注编排。
行为与原实现完全一致，仅做机械搬迁。
"""

import logging

from app.services.qc_engine.rubric import Rubric
from app.services.qc_engine.rubrics.zj_inpatient_2021 import ZJ_INPATIENT_V2021
from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
    ZJ_OUTPATIENT_EMERGENCY_V2023,
)
from app.services.qc_engine.scorer import ScoreReport

logger = logging.getLogger(__name__)


# 住院系列 record_type 白名单——治本动机（2026-05-19）：
# 原占位实现让住院类全部回退用门急诊 rubric，导致门急诊规则在住院首次病程上
# 误报（"无就诊时间"等）。现在按 record_type 精确路由到住院 rubric。
_INPATIENT_RECORD_TYPES = frozenset({
    "admission_note",
    "first_course_record",
    "course_record",
    "senior_round",
    "discharge_record",
    "pre_op_summary",
    "op_record",
    "post_op_record",
})


def _select_rubric(record_type: str | None) -> Rubric:
    """按 record_type 选择对应法定评分表。

    路由策略：
      - outpatient / emergency → 门急诊 rubric（PDF 2023 版，11 大项 100 分）
      - admission_note / first_course_record / course_record / senior_round /
        discharge_record / pre_op_summary / op_record / post_op_record
        → 住院 rubric（PDF 2021 版，18 大项 100 分，含单项否决 + 甲乙丙三级）

    住院 rubric 内每条规则按 record_type 自适应触发（checker 第一行做守卫），
    医生在 admission_note 跑质控只触发入院记录区规则、在 first_course_record 跑
    只触发首次病程规则——一份 rubric 覆盖 8 种住院 record_type。
    """
    rt = record_type or "outpatient"
    if rt in ("outpatient", "emergency"):
        return ZJ_OUTPATIENT_EMERGENCY_V2023
    if rt in _INPATIENT_RECORD_TYPES:
        return ZJ_INPATIENT_V2021
    # 兜底：未识别的 record_type（不该走到这里）默认门急诊评分
    logger.warning("qc.select_rubric: 未识别的 record_type=%r，回退门急诊评分", rt)
    return ZJ_OUTPATIENT_EMERGENCY_V2023


def _deductions_to_issues(report: ScoreReport) -> list[dict]:
    """ScoreReport 扣分列表 → 前端 qcIssues 兼容结构。

    前端依赖的字段（保持兼容）：
      - risk_level: high/medium/low（按扣分值粗映射）
      - field_name: 大项名（用于行级"已写入"修复）
      - issue_description / suggestion / score_impact
      - source: "rule"（必修复，参与等级判定）/ "llm"（旁路建议）
    """
    issues: list[dict] = []
    for d in report.deductions:
        # 扣分值 → 风险等级（用于前端按红/黄/灰分组显示）
        if d.is_veto or d.points >= 5:
            level = "high"
        elif d.points >= 2:
            level = "medium"
        else:
            level = "low"
        issues.append({
            "risk_level": level,
            # 治本（2026-05-19）：优先用规则自带 target_field（精确到病历子字段），
            # 无 target_field 时退到大项名（适用大项与单字段 1:1 映射的场景）。
            # 这让前端"逐条修复 → 写入病历"能精准替换合并章节下的某一子行
            # （如【治疗意见及措施】下的"治则治法：xxx"行），而不是把修复文本
            # 兜底追加到病历末尾。
            "field_name": d.target_field or d.item_name,
            # 治本配套（2026-05-19）：大项名独立透传，跟 field_name（写入目标）解耦。
            # 前端 QCIssuePanel 按 PDF 大项分组渲染时用此字段，
            # 避免 target_field 变成子字段名后跟 score_report.items[].name 对不上。
            "item_name": d.item_name,
            "rule_code": d.rule_code,
            "issue_description": d.description,
            "suggestion": d.description,  # PDF 扣分说明本身即为修复指引
            "score_impact": f"-{d.points}分",
            "is_veto": d.is_veto,
            "source": "rule",
        })
    return issues
