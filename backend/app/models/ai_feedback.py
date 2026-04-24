"""
AI 建议反馈模型（models/ai_feedback.py）

用途：
  医生对 AI 生成的追问/检查/诊断建议点「有用 / 无用」的反馈日志。
  这批数据攒够规模后（~500+）用于 prompt 工程 / RAG 负例 / 未来微调语料。

地基设计要点（为什么要存 prompt_version 和 model_name）：
  prompt 和模型都会演进；同一条"盗汗追问"在 v1 prompt 下被踩，不代表 v2 prompt
  下还差。将来做档次 2（塞负例回 prompt）时必须按 (prompt_version, model_name)
  两个维度过滤，否则会把旧 prompt 的反馈污染进新 prompt，产生方向性错误。
  这两字段现在补 5 分钟，以后省 N 天数据重新攒的时间。

字段：
  - suggestion_category：追问 / 检查 / 诊断（inquiry/exam/diagnosis）
  - suggestion_text：被反馈的建议文本（冗余存储，避免 AI 原始响应未落库时无从回溯）
  - verdict：useful / useless
  - comment：医生留言（可选，文字反馈价值 >> 二元）
  - prompt_version：生成该建议时使用的 prompt 模板版本（从 prompt_templates.version 取）
  - prompt_scene：prompt 的 scene（对应 prompt_templates.scene）
  - model_name：生成该建议的模型名（从 model_configs 或实际调用响应取）
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class AISuggestionFeedback(Base, TimestampMixin):
    """医生对 AI 建议的点赞/点踩日志。"""

    __tablename__ = "ai_suggestion_feedback"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[Optional[str]] = mapped_column(String, index=True)
    doctor_id: Mapped[Optional[str]] = mapped_column(String, index=True)

    suggestion_category: Mapped[str] = mapped_column(String(20), index=True)
    suggestion_id: Mapped[Optional[str]] = mapped_column(String(100))
    suggestion_text: Mapped[str] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String(10))
    comment: Mapped[Optional[str]] = mapped_column(Text)

    # 以下三项为"地基字段"，用来做未来档次 2/3 的关键分层维度
    prompt_version: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    prompt_scene: Mapped[Optional[str]] = mapped_column(String(50))
    model_name: Mapped[Optional[str]] = mapped_column(String(100))

    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
