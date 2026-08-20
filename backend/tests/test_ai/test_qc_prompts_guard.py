# -*- coding: utf-8 -*-
"""质控修复 prompt 红线守卫测试。

2026-08-20 第三轮走查在生产实锤两类编造：
  - 逐条修复给望诊编造病理性阳性所见（"面色少华"）
  - 批量补全给既往史编造否认清单，且否认了病历里已诊断的病（诊断=高血压病，
    补全写"否认高血压"）
修法是在 QC_FIX_PROMPT / QC_FIX_BATCH_PROMPT 里加"阳性所见红线"和"病史红线"。
prompt 是纯文本、改动无编译期保护，这里做静态守卫：红线关键句被删/被改就红。
"""

from app.services.ai.prompts_qc import QC_FIX_BATCH_PROMPT, QC_FIX_PROMPT


def test_fix_prompts_contain_positive_findings_redline():
    """两个修复 prompt 都必须保留"不编造病理性阳性所见"红线。"""
    for prompt in (QC_FIX_PROMPT, QC_FIX_BATCH_PROMPT):
        assert "阳性所见红线" in prompt
        assert "面色少华" in prompt  # 反例示范必须在场，LLM 对具体反例更敏感
        assert "中性常规描述" in prompt


def test_fix_prompts_contain_history_denial_redline():
    """两个修复 prompt 都必须保留"病史不得编造否认式陈述"红线。"""
    for prompt in (QC_FIX_PROMPT, QC_FIX_BATCH_PROMPT):
        assert "病史红线" in prompt
        assert "否认" in prompt
        # 最致命的自相矛盾场景必须点名：否认病历里已诊断的病
        assert "高血压" in prompt


def test_fix_prompts_keep_treatment_keyword_cheatsheet():
    """关键词速查表仍在（与质控规则 OP-PRESENT-ILLNESS-02 对齐，缺了修复后仍扣分）。"""
    for prompt in (QC_FIX_PROMPT, QC_FIX_BATCH_PROMPT):
        assert "治疗" in prompt and "服药" in prompt
