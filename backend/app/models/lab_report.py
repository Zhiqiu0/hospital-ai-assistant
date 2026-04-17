"""
检验报告 ORM 模型（models/lab_report.py）

数据表：
  lab_reports : 检验单上传记录，含原始文件路径和 AI OCR 识别结果

数据流：
  1. 医生上传检验单图片/PDF → 创建记录（status="uploaded"）
  2. 后端调用 LLM 进行 OCR 识别 → 结构化文本写入 ocr_text（status="done"）
  3. 识别结果展示在工作台右侧「检验单」标签页，供医生参考
  4. 医生可选择将关键数据插入病历

文件存储：
  上传文件保存到 backend/uploads/lab_reports/{encounter_id}/{uuid}.{ext}
  file_path 存储相对于 uploads/ 的路径
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class LabReport(Base, TimestampMixin):
    """检验报告表（每次上传一张/一份检验单对应一条记录）。

    status 状态说明：
      uploaded  : 文件已上传，等待 OCR 处理
      analyzing : OCR 处理中
      done      : OCR 完成，ocr_text 有内容
      failed    : OCR 失败（原因可在日志中查找）
    """

    __tablename__ = "lab_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 关联接诊（可空：允许独立上传不绑定接诊）
    encounter_id: Mapped[Optional[str]] = mapped_column(ForeignKey("encounters.id"))
    # 上传的医生
    doctor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"))
    # 原始文件名（保留给用户看，便于识别是哪张化验单）
    original_filename: Mapped[Optional[str]] = mapped_column(String(300))
    # 服务器存储路径（相对于 uploads/ 目录）
    file_path: Mapped[Optional[str]] = mapped_column(String(500))
    # 文件 MIME 类型："image/jpeg"/"image/png"/"application/pdf" 等
    mime_type: Mapped[Optional[str]] = mapped_column(String(100))
    # AI OCR 识别出的结构化文本（格式化的检验项目和结果）
    ocr_text: Mapped[Optional[str]] = mapped_column(Text)
    # 处理状态
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    # OCR 完成时间
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 关联上传医生
    doctor: Mapped[Optional["User"]] = relationship(foreign_keys=[doctor_id])


# 延迟导入避免循环引用
from app.models.user import User  # noqa: E402, F401
