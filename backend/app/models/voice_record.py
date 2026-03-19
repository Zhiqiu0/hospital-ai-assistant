import json
from typing import Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class VoiceRecord(Base, TimestampMixin):
    __tablename__ = "voice_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("encounters.id"))
    doctor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    visit_type: Mapped[Optional[str]] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    raw_transcript: Mapped[Optional[str]] = mapped_column(Text)
    audio_file_path: Mapped[Optional[str]] = mapped_column(String(300))
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    transcript_summary: Mapped[Optional[str]] = mapped_column(Text)
    speaker_dialogue: Mapped[Optional[str]] = mapped_column(Text)
    structured_inquiry: Mapped[Optional[str]] = mapped_column(Text)
    draft_record: Mapped[Optional[str]] = mapped_column(Text)

    def get_speaker_dialogue(self) -> list:
        if not self.speaker_dialogue:
            return []
        try:
            return json.loads(self.speaker_dialogue)
        except Exception:
            return []

    def get_structured_inquiry(self) -> dict:
        if not self.structured_inquiry:
            return {}
        try:
            return json.loads(self.structured_inquiry)
        except Exception:
            return {}
