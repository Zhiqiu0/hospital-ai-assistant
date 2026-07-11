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

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, text
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

    # 与真实 DB 对齐：id_card 上的「部分唯一索引」（由 alembic b8c9d0e1f2a3 建），
    # 保证「同一身份证只允许一份活跃档案」（NULL 及已软删记录不参与唯一）。
    # 原 model 未声明 → autogenerate 判为「需删除」。这里显式复刻其 WHERE 谓词。
    # postgresql_where / sqlite_where 同时给出：SQLite 3.45 也支持部分索引，
    # 让测试库 create_all 出的索引与 PG 语义一致，避免整列唯一误伤查重测试。
    __table_args__ = (
        Index(
            "uq_patients_id_card_active",
            "id_card",
            unique=True,
            postgresql_where=text("id_card IS NOT NULL AND is_deleted = false"),
            sqlite_where=text("id_card IS NOT NULL AND is_deleted = false"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # HIS 系统患者编号，全局唯一（HIS 同步来的患者才有）
    patient_no: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    # 患者真实姓名（必填）
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 姓名拼音索引：覆盖全拼/首字母/混拼（"zhangsan" / "zs" / "zhangs" / "zsan"）。
    # 多字 + 多音字时所有 2^N 组合用空格分隔，由 utils.pinyin.compute_pinyin 生成。
    # 写入时机：PatientService.create / update 自动回填，不需要调用方关心。
    name_pinyin: Mapped[Optional[str]] = mapped_column(String(512))
    # 姓名首字母索引：仅纯首字母组合（"zs"），保留作未来精排（首字母完全匹配优先）。
    name_pinyin_initials: Mapped[Optional[str]] = mapped_column(String(128))
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

    # ── 软删除字段（2026-05-03 加，配合接诊取消联动清理孤儿档案）─────────────
    # 业务规则：取消接诊时如果患者本身是这次接诊一并新建（无其他 encounter、
    # 非 HIS 来源），则把患者一并软删；老患者复诊取消不动这里。
    # 所有患者搜索/查重入口（PatientService.search / find_existing / get_by_id）
    # 必须过滤 is_deleted=false。物理删会丢审计，所以走软删保留行。
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    deleted_by: Mapped[Optional[str]] = mapped_column(String, ForeignKey("users.id"))

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
    # 旧的 profile_past_history 等 8 个 TEXT 列 + profile_updated_at 在 DB 中保留作
    # 历史归档，数据已由 schema_compat 的迁移 SQL 一次性搬入本 JSONB 字段。
    profile: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # ── 【已弃用】旧扁平档案列（DEPRECATED，保留以对齐真实 DB，勿再读写）──────────
    # 现役档案统一走上面的 profile JSONB；这 9 个 TEXT/TIMESTAMP 列是 JSONB 重构前
    # 的老结构，数据已迁移完毕，业务代码不再引用。之所以在 model 里「显式声明」而非
    # 沉默丢弃：它们真实存在于生产 DB，声明出来才能让 alembic check 归零（零 DB 改动、
    # 零数据风险）。真正的物理 drop_column 属高风险不可逆操作，留作未来单独审慎迁移。
    profile_past_history: Mapped[Optional[str]] = mapped_column(Text)
    profile_allergy_history: Mapped[Optional[str]] = mapped_column(Text)
    profile_family_history: Mapped[Optional[str]] = mapped_column(Text)
    profile_personal_history: Mapped[Optional[str]] = mapped_column(Text)
    profile_current_medications: Mapped[Optional[str]] = mapped_column(Text)
    profile_marital_history: Mapped[Optional[str]] = mapped_column(Text)
    profile_menstrual_history: Mapped[Optional[str]] = mapped_column(Text)
    profile_religion_belief: Mapped[Optional[str]] = mapped_column(Text)
    profile_updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    # 该患者的所有接诊记录（按时间倒序使用时在服务层处理）
    encounters: Mapped[list["Encounter"]] = relationship(back_populates="patient")


# 延迟导入避免循环引用（Patient ↔ Encounter 互相引用）
from app.models.encounter import Encounter  # noqa: E402
