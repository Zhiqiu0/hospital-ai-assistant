"""
AI 提示词库（Prompt Library）— 向后兼容导出入口

L3 治本路线后的精简版：
  - 病历生成 prompt 已不再以"自由文本字符串模板"形式存在；
    各 record_type 的 schema + renderer 由 services/ai/record_schemas + record_renderer 维护，
    prompt 由 services/ai/record_prompts 在请求时按 schema 动态构造。
  - 本文件仅 re-export 仍以"字符串模板"形式存在的 prompt：
    voice 结构化 / 病历续写补全润色 / 问诊建议 / QC 等。
  - RECORD_TYPE_LABELS 迁到 record_schemas.py，本文件转发引用。
"""

from app.services.ai.prompts_voice import (  # noqa: F401
    VOICE_STRUCTURE_PROMPT_INPATIENT,
    VOICE_STRUCTURE_PROMPT_OUTPATIENT,
)
from app.services.ai.prompts_operations import (  # noqa: F401
    CONTINUE_PROMPT,
    POLISH_PROMPT,
    SUPPLEMENT_PROMPT,
)
from app.services.ai.prompts_suggestions import (  # noqa: F401
    DIAGNOSIS_SUGGESTION_PROMPT,
    EXAM_SUGGESTIONS_PROMPT,
    INQUIRY_SUGGESTIONS_PROMPT,
)
from app.services.ai.prompts_qc import (  # noqa: F401
    GRADE_SCORE_PROMPT,
    QC_FIX_PROMPT,
    QC_PROMPT,
)
from app.services.ai.record_schemas import RECORD_TYPE_LABELS  # noqa: F401

# RECORD_TYPE_MAP 是 RECORD_TYPE_LABELS 的旧别名，保留兼容老引用。
RECORD_TYPE_MAP = RECORD_TYPE_LABELS
