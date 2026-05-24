"""病历质控引擎（services/qc_engine）

L3 治本架构：按浙江省卫健委评分标准 1:1 映射 + 三层架构。

模块边界：
  - section.py      : Section 值对象，is_filled 是"是否已填写"的全项目唯一权威
  - rubric.py       : 评分表数据结构（DeductionRule / VetoRule / RubricItem / Rubric）
  - parser.py       : 病历文本 → Section dict（占位符 / 空值在此就过滤，下游永不再判）
  - scorer.py       : 评分器（大项上限保护 + 单项否决短路 + PDF 等级判定）
  - rubrics/        : 法定评分表代码常量（PR review 才能改，admin 不可改）
    └── zj_outpatient_emergency_2023.py
    └── zj_inpatient_2021.py（下一期）

为什么独立成 qc_engine 而不放 rule_engine：
  - rule_engine/completeness_rules.py 是旧实现，多个阶段散落判定占位符 → bug
  - 新架构治本：所有判定收编到 Section.is_filled() 一处
  - 老 rule_engine 在新引擎稳定后整体删除（参考 record_gen_v2 取代旧 stream_text 的节奏）
"""
