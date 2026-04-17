"""
语音录音 ORM 模型（models/voice_record.py）

数据表：
  voice_records : 每次录音上传对应一条记录，含原始音频路径和转写/结构化结果

数据流：
  1. 医生录音完毕 → 上传音频文件（status="uploaded"）
  2. 后端执行 ASR 转写（Qwen-Audio-Turbo 或浏览器原生）→ raw_transcript
  3. 医生点击「AI分析并整理」→ 结构化为问诊字段（status="structured"）
  4. 结构化结果回填到 InquiryInput，语音记录作为原始证据保留

存储说明：
  音频文件存储在 backend/uploads/voice_records/{encounter_id}/{uuid}.webm
  audio_file_path 存储相对于 uploads 目录的路径
  speaker_dialogue / structured_inquiry 以 JSON 字符串存储（方便 PostgreSQL Text 字段兼容）
"""

import json
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class VoiceRecord(Base, TimestampMixin):
    """语音录音记录表。

    每条录音对应一次接诊中的一段语音输入（可多次录音）。
    """

    __tablename__ = "voice_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 关联接诊（可空：允许不绑定接诊直接录音）
    encounter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("encounters.id"))
    # 录音的医生
    doctor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    # 就诊类型，影响 AI 结构化时使用的 prompt："outpatient"/"inpatient"/"emergency"
    visit_type: Mapped[Optional[str]] = mapped_column(String(20))
    # 处理状态："uploaded"（刚上传）/ "structured"（已完成 AI 结构化）
    status: Mapped[str] = mapped_column(String(20), default="uploaded")

    # ── 转写文本 ──────────────────────────────────────────────────────────────
    # 原始转写文本（浏览器端 SpeechRecognition 或 Qwen-Audio-Turbo 转写结果）
    raw_transcript: Mapped[Optional[str]] = mapped_column(Text)

    # ── 文件存储 ──────────────────────────────────────────────────────────────
    # 音频文件相对路径（相对于 uploads/ 目录），如 "voice_records/enc-xxx/uuid.webm"
    audio_file_path: Mapped[Optional[str]] = mapped_column(String(300))
    # 音频 MIME 类型，如 "audio/webm;codecs=opus"（用于 Content-Type 响应头）
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))

    # ── AI 结构化结果（status="structured" 后填入）─────────────────────────────
    # 对话摘要（简短文字描述本次录音内容）
    transcript_summary: Mapped[Optional[str]] = mapped_column(Text)
    # 医患对话角色分析（JSON 字符串，格式见 get_speaker_dialogue）
    speaker_dialogue: Mapped[Optional[str]] = mapped_column(Text)
    # 结构化后的问诊字段（JSON 字符串，格式与 InquiryInput 字段对应）
    structured_inquiry: Mapped[Optional[str]] = mapped_column(Text)
    # AI 生成的病历草稿（基于本次录音内容）
    draft_record: Mapped[Optional[str]] = mapped_column(Text)

    # 关联录音医生（用于权限控制：只有本人可以访问/删除）
    doctor: Mapped[Optional["User"]] = relationship(foreign_keys=[doctor_id])

    def get_speaker_dialogue(self) -> list:
        """将 speaker_dialogue JSON 字符串反序列化为列表。

        Returns:
            对话角色分析列表，每项格式：{"speaker": "doctor"|"patient"|"uncertain", "text": "..."}
            解析失败时返回空列表，保证调用方不需要处理异常。
        """
        if not self.speaker_dialogue:
            return []
        try:
            return json.loads(self.speaker_dialogue)
        except Exception:
            return []

    def get_structured_inquiry(self) -> dict:
        """将 structured_inquiry JSON 字符串反序列化为字典。

        Returns:
            结构化问诊字段字典（key 与 InquiryInput 字段名对应）。
            解析失败时返回空字典。
        """
        if not self.structured_inquiry:
            return {}
        try:
            return json.loads(self.structured_inquiry)
        except Exception:
            return {}


# 延迟导入避免循环引用
from app.models.user import User  # noqa: E402
