"""
影像检查 ORM 模型（models/imaging.py）

数据表：
  imaging_studies  : 影像检查主表（一次 CT/MR/DR 对应一条）
  imaging_reports  : 影像报告表（每条检查对应一份报告，1:1 关系）

数据流：
  1. 上传 DICOM/ZIP 文件 → 创建 ImagingStudy（status="pending"）
  2. 后端解压、提取关键帧 → 更新 total_frames / storage_dir
  3. 调用 Qwen-VL-Plus 分析选中帧 → 写入 ai_analysis（status="analyzing" → "analyzed"）
  4. 影像科医生审核，修改 AI 结果 → 写入 final_report（status="published"）

存储说明：
  DICOM 文件解压到 backend/uploads/imaging/{uuid}/ 目录
  storage_dir 存储该目录的绝对路径（或相对于 uploads 的路径）
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class ImagingStudy(Base, TimestampMixin):
    """影像检查主表（一次影像检查 = 一条记录）。

    modality 可选值（DICOM 标准）：
      CT  : 电子计算机断层扫描
      MR  : 核磁共振
      DR  : 数字 X 线摄影
      US  : 超声
    """

    __tablename__ = "imaging_studies"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 关联患者（必填）
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), nullable=False)
    # 上传该影像的医生（必填）
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    # ── 影像元数据（从 DICOM 文件头提取）────────────────────────────────────
    # 检查设备类型："CT" / "MR" / "DR" / "US"
    modality: Mapped[Optional[str]] = mapped_column(String(20))
    # 检查部位，如："胸部" / "腹部" / "头颅"
    body_part: Mapped[Optional[str]] = mapped_column(String(100))
    # 序列描述（DICOM Series Description 字段）
    series_description: Mapped[Optional[str]] = mapped_column(String(200))
    # 检查日期（从 DICOM 元数据读取）
    study_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # 总切片数（DICOM 文件数量），用于前端进度展示
    total_frames: Mapped[int] = mapped_column(Integer, default=0)

    # ── 文件存储 ──────────────────────────────────────────────────────────────
    # DICOM 解压后的目录路径（存储在服务器本地）
    storage_dir: Mapped[str] = mapped_column(String(500))

    # ── 状态流转 ──────────────────────────────────────────────────────────────
    # pending   : 刚上传，等待 AI 分析
    # analyzing : AI 分析中
    # analyzed  : AI 分析完成，待影像科医生审核
    # published : 报告已审核发布
    status: Mapped[str] = mapped_column(String(20), default="pending")

    # 关联的影像报告（一对一，uselist=False）
    report: Mapped[Optional["ImagingReport"]] = relationship(
        back_populates="study", uselist=False
    )


class ImagingReport(Base, TimestampMixin):
    """影像报告表（一条 ImagingStudy 对应一份报告）。

    AI 分析结果（ai_analysis）和最终报告（final_report）分开存储：
      - ai_analysis  : Qwen-VL-Plus 原始分析文本（保留供参考/对比）
      - final_report : 影像科医生审核修改后的最终报告（发布给临床医生使用）
    """

    __tablename__ = "imaging_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 关联影像检查（唯一约束：一份检查只能有一份报告）
    study_id: Mapped[str] = mapped_column(
        ForeignKey("imaging_studies.id"), nullable=False, unique=True
    )
    # 撰写/分析报告的影像科医生（可空：AI 自动生成的报告暂无审核医生）。
    # 在 analyze_study 阶段写入，**不应被 publish 阶段覆盖**——历史 bug：
    # 曾经 publish_report 直接 `report.radiologist_id = current_user.id`，
    # 让"A 分析、B 发布"场景下分析人被误改为 B，造成审计断链。
    radiologist_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    # 实际签发（发布）报告的影像科医生，可与 radiologist_id 不同（如 A 分析 + B 复核签发）。
    # 由 publish_report 端点写入，是审计链的"签发责任人"字段。
    published_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))

    # 用户选中的关键帧文件名列表（JSON 数组，如 ["0001.DCM", "0050.DCM"]）
    # 只有选中的帧会发送给 AI 分析，避免切片过多超出 token 限制
    selected_frames: Mapped[Optional[Any]] = mapped_column(JSONB)

    # AI 分析原始文本（Qwen-VL-Plus 输出，未经医生修改）
    ai_analysis: Mapped[Optional[str]] = mapped_column(Text)

    # 影像科医生最终审核报告（基于 ai_analysis 修改，或完全重写）
    final_report: Mapped[Optional[str]] = mapped_column(Text)

    # 是否已发布（发布后临床医生可看到报告）
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    # 发布时间
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 反向关联影像检查
    study: Mapped["ImagingStudy"] = relationship(back_populates="report")
