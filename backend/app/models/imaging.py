# -*- coding: utf-8 -*-
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped, relationship
from typing import Optional, Any
from datetime import datetime
from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class ImagingStudy(Base, TimestampMixin):
    """影像检查主表"""
    __tablename__ = "imaging_studies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    # 影像元数据（从 DICOM 读取）
    modality: Mapped[Optional[str]] = mapped_column(String(20))        # CT / MR / DR / US
    body_part: Mapped[Optional[str]] = mapped_column(String(100))      # 检查部位
    series_description: Mapped[Optional[str]] = mapped_column(String(200))
    study_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    total_frames: Mapped[int] = mapped_column(Integer, default=0)      # 总切片数

    # 文件存储
    storage_dir: Mapped[str] = mapped_column(String(500))              # 解压后的目录路径

    # 状态: pending(待分析) / analyzing / analyzed(待审核) / published(已发布)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    # 关联
    report: Mapped[Optional["ImagingReport"]] = relationship(back_populates="study", uselist=False)


class ImagingReport(Base, TimestampMixin):
    """影像报告表"""
    __tablename__ = "imaging_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    study_id: Mapped[str] = mapped_column(ForeignKey("imaging_studies.id"), nullable=False, unique=True)
    radiologist_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))

    # 选中的关键帧（文件名列表）
    selected_frames: Mapped[Optional[Any]] = mapped_column(JSONB)      # ["0001.DCM", "0050.DCM", ...]

    # AI 分析原始结果
    ai_analysis: Mapped[Optional[str]] = mapped_column(Text)

    # 影像科医生最终报告（可修改 AI 结果）
    final_report: Mapped[Optional[str]] = mapped_column(Text)

    # 发布状态
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    study: Mapped["ImagingStudy"] = relationship(back_populates="report")
