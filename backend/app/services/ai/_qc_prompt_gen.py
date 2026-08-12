"""QC 提示词标准段生成器（services/ai/_qc_prompt_gen.py）

2026-08-12 质控双真相源收口：
问题：QC_PROMPT 里手写内嵌了一份"检查标准"，与真正驱动扣分的法定评分表
（qc_engine.rubrics 代码常量）是两份各自维护的文本——评分表按 PDF 修订后，
提示词不会跟着变，医生看到的 AI 建议口径就和实际扣分口径打架。

方案：提示词里的标准段改为从评分表常量**运行时生成**（本模块），
单一真相源=qc_engine.rubrics。评分表改一处，AI 建议口径自动同步。

边界（关键，防止回到"修不到 100 分"的老问题）：
  - 本模块只生成提示词文本，**完全不碰打分链路**——打分仍由
    qc_engine.scorer.score(rubric, ctx) 规则引擎驱动，LLM 输出不参与总分
    （见 qc_stream_service：llm_issues 不计入 must_fix_count / grade_score）。
"""
from app.services.qc_engine.rubric import Rubric, VETO_DEDUCT_POINTS


def _format_points(points: float) -> str:
    """扣分值格式化：整数不带小数点（2 而非 2.0），0.5 保留。"""
    return f"{points:g}"


def build_qc_standard_block(rubric: Rubric) -> str:
    """把一份法定评分表渲染成 QC_PROMPT 的"检查标准"文本段。

    输出示例（节选）：
        ━━━ 法定评分标准：浙江省中医住院病历评分标准（2021 版，总分 100 分）━━━
        等级判定：甲级（≥90 分）/ 乙级（≥80 分）/ 丙级（<80 分）

        1、主诉（2 分）
        检查要求：……
        - 【单项否决】主要诊断填写或编码错误（扣 10 分，该大项不再累积扣分）
        - 主要症状、体征描述不清（扣 0.5 分）
    """
    lines: list[str] = [
        f"━━━ 法定评分标准：{rubric.name}（{rubric.version} 版，"
        f"总分 {_format_points(rubric.total_points)} 分）━━━"
    ]

    # 等级判定行：最高等级显示 ≥ 自身阈值，其余显示 < 上一级阈值（与展示页口径一致）
    grade_parts: list[str] = []
    for idx, t in enumerate(rubric.grade_thresholds):
        if idx == 0:
            grade_parts.append(f"{t.label}（≥{_format_points(t.min_score)} 分）")
        else:
            upper = rubric.grade_thresholds[idx - 1].min_score
            grade_parts.append(f"{t.label}（<{_format_points(upper)} 分）")
    if grade_parts:
        lines.append("等级判定：" + " / ".join(grade_parts))

    for idx, item in enumerate(rubric.items, 1):
        lines.append("")
        lines.append(f"{idx}、{item.name}（{_format_points(item.max_points)} 分）")
        if item.description:
            lines.append(f"检查要求：{item.description}")
        for veto in item.veto_rules:
            # 与引擎实际扣分对齐（2026-08-12 复检修复）：scorer 对 veto 的实际
            # 扣分是 min(10, 大项分值)——如"首次病程录"仅 6 分，触发只扣 6 分。
            # 原来统一渲染"扣 10 分"会让 AI 建议口径与真实扣分打架。
            effective = min(VETO_DEDUCT_POINTS, item.max_points)
            lines.append(
                f"- 【单项否决】{veto.description}"
                f"（扣 {_format_points(effective)} 分，该大项不再累积扣分）"
            )
        for rule in item.deduction_rules:
            lines.append(
                f"- {rule.description}（扣 {_format_points(rule.deduct_points)} 分）"
            )

    return "\n".join(lines)
