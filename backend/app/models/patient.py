"""
患者 ORM 模型（models/patient.py）

数据表：
  patients : 患者主档，存储基本人口学信息及病案首页所需字段

数据来源：
  is_from_his=True  : 由 HIS 系统同步导入，patient_no 有值
  is_from_his=False : 通过系统门诊/急诊接诊页手动录入

查重策略（PatientService.find_existing）：
  优先按身份证号精确匹配，其次按 (姓名+出生日期+手机号) 模糊匹配，
  避免同一患者重复建档。
"""

import datetime
from typing import Optional

from sqlalchemy import Boolean, Date, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class Patient(Base, TimestampMixin):
    """患者主档表。

    字段说明：
      patient_no    : HIS 系统患者编号（HIS 同步时填入，手动录入时为空）
      id_card       : 居民身份证号，长度 18 位，可用于精确查重
      is_from_his   : 区分 HIS 导入患者和手动录入患者，避免双向同步冲突
      blood_type    : 血型，如 "A"/"B"/"AB"/"O"，可带 Rh 标注 "A+"/"O-"
    """

    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # HIS 系统患者编号，全局唯一（HIS 同步来的患者才有）
    patient_no: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    # 患者真实姓名（必填）
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 性别："男" / "女" / "未知"
    gender: Mapped[Optional[str]] = mapped_column(String(10))
    # 出生日期（用于计算年龄、匹配复诊历史）
    birth_date: Mapped[Optional[datetime.date]] = mapped_column(Date)
    # 居民身份证号，用于患者精确查重
    id_card: Mapped[Optional[str]] = mapped_column(String(20))
    # 联系电话
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    # 家庭住址
    address: Mapped[Optional[str]] = mapped_column(String)
    # 是否来自 HIS 系统：True=HIS 导入，False=系统手动录入
    is_from_his: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── 病案首页扩展字段（住院病历必填）────────────────────────────────────────
    # 民族
    ethnicity: Mapped[Optional[str]] = mapped_column(String(20))
    # 婚姻状况："未婚" / "已婚" / "离婚" / "丧偶"
    marital_status: Mapped[Optional[str]] = mapped_column(String(10))
    # 职业（文本，不做枚举限定）
    occupation: Mapped[Optional[str]] = mapped_column(String(100))
    # 工作单位
    workplace: Mapped[Optional[str]] = mapped_column(String(200))
    # 紧急联系人姓名
    contact_name: Mapped[Optional[str]] = mapped_column(String(50))
    # 紧急联系人电话
    contact_phone: Mapped[Optional[str]] = mapped_column(String(20))
    # 紧急联系人与患者关系："配偶" / "子女" / "父母" 等
    contact_relation: Mapped[Optional[str]] = mapped_column(String(20))
    # 血型
    blood_type: Mapped[Optional[str]] = mapped_column(String(10))

    # ── 患者档案（Longitudinal Patient Record，JSONB 重构后）─────────────────
    # 单一 JSONB 字段存全部档案，支持字段级 updated_at + updated_by（FHIR
    # verificationStatus 思路）。结构：
    #   {
    #     "past_history":     {"value": "高血压5年", "updated_at": "...", "updated_by": "doc_xxx"},
    #     "allergy_history":  {"value": "否认",       "updated_at": "...", "updated_by": "..."},
    #     ... 共 7 个字段（月经史已移除——时变信息走 inquiry_inputs.menstrual_history）
    #   }
    # 字段不存在 = 该项档案从未录入；字段存在但 value 为空 = 显式置空。
    # 旧的 profile_past_history 等 8 个 TEXT 列在 DB 中保留作历史归档，model 不再映射，
    # 由 schema_compat 的迁移 SQL 把数据搬到本字段。
    profile: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # 该患者的所有接诊记录（按时间倒序使用时在服务层处理）
    encounters: Mapped[list["Encounter"]] = relationship(back_populates="patient")


# 延迟导入避免循环引用（Patient ↔ Encounter 互相引用）
from app.models.encounter import Encounter  # noqa: E402
