"""
住院模块 ORM 模型（models/inpatient.py）

数据表：
  vital_signs  : 生命体征记录（体温/脉搏/呼吸/血压/血氧/身高/体重）
  problem_list : 问题列表（住院期间活跃诊断/问题清单）

设计说明：
  每次测量生命体征创建一条 VitalSign 记录（同一接诊可有多条，时序展示）。
  ProblemItem 跟踪住院期间的活跃问题，status=resolved 表示已解决。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class VitalSign(Base, TimestampMixin):
    """生命体征记录表（每次测量产生一条记录）。"""

    __tablename__ = "vital_signs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # 记录时间（允许手动填写过去时间点，默认为当前时间）
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    temperature: Mapped[Optional[float]] = mapped_column(Float)    # 体温 °C
    pulse: Mapped[Optional[int]] = mapped_column(Integer)          # 脉搏 次/min
    respiration: Mapped[Optional[int]] = mapped_column(Integer)    # 呼吸 次/min
    bp_systolic: Mapped[Optional[int]] = mapped_column(Integer)    # 收缩压 mmHg
    bp_diastolic: Mapped[Optional[int]] = mapped_column(Integer)   # 舒张压 mmHg
    spo2: Mapped[Optional[int]] = mapped_column(Integer)           # 血氧饱和度 %
    weight: Mapped[Optional[float]] = mapped_column(Float)         # 体重 kg
    height: Mapped[Optional[float]] = mapped_column(Float)         # 身高 cm
    notes: Mapped[Optional[str]] = mapped_column(Text)             # 备注
    recorded_by: Mapped[Optional[str]] = mapped_column(String(50)) # 记录医生姓名


class ProblemItem(Base, TimestampMixin):
    """问题列表条目（住院期间活跃诊断 / 临床问题）。

    status 取值：
      active   : 活跃问题（默认）
      resolved : 已解决
    """

    __tablename__ = "problem_list"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    encounter_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    problem_name: Mapped[str] = mapped_column(String(200), nullable=False) # 问题/诊断名称
    icd_code: Mapped[Optional[str]] = mapped_column(String(20))            # ICD 编码
    onset_date: Mapped[Optional[str]] = mapped_column(String(30))          # 发病/发现日期
    status: Mapped[str] = mapped_column(String(20), default="active")      # active/resolved
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)       # 是否主要诊断
    added_by: Mapped[Optional[str]] = mapped_column(String(50))            # 添加医生姓名
