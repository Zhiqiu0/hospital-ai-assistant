"""
AI 提示词库（Prompt Library）— 向后兼容导出入口

各域 prompt 已拆分至独立模块，按需导入：
  - prompts_voice       语音结构化
  - prompts_generation  病历生成（门诊 / 住院各类型）+ RECORD_TYPE_LABELS + PROMPT_MAP
  - prompts_operations  病历润色 / 续写 / 补全
  - prompts_suggestions 问诊建议 / 检查建议 / 诊断建议
  - prompts_qc          质控（QC）/ 质控修复 / 甲级评分

本文件保持所有名称可用，避免修改存量 import。
"""

from app.services.ai.prompts_voice import (  # noqa: F401
    VOICE_STRUCTURE_PROMPT_INPATIENT,
    VOICE_STRUCTURE_PROMPT_OUTPATIENT,
)
from app.services.ai.prompts_generation import (  # noqa: F401
    ADMISSION_NOTE_PROMPT,
    COURSE_RECORD_PROMPT,
    DISCHARGE_RECORD_PROMPT,
    FIRST_COURSE_PROMPT,
    OP_RECORD_PROMPT,
    OUTPATIENT_GENERATE_PROMPT,
    POST_OP_RECORD_PROMPT,
    PRE_OP_SUMMARY_PROMPT,
    PROMPT_MAP,
    RECORD_TYPE_LABELS,
    SENIOR_ROUND_PROMPT,
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

# RECORD_TYPE_MAP was a duplicate of RECORD_TYPE_LABELS — kept as alias for
# any code that still references the old name.
RECORD_TYPE_MAP = RECORD_TYPE_LABELS
