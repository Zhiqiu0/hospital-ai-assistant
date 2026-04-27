"""
患者相关 Pydantic 模型（schemas/patient.py）

包含：
  PatientCreate      : 创建患者的入参
  PatientUpdate      : 更新患者信息的入参（所有字段可选）
  PatientResponse    : 患者查询响应（含计算字段 age）
  PatientListResponse: 患者列表分页响应

注意：
  PatientResponse 包含 age（由出生日期计算），不是 DB 字段，
  由 PatientService.get_xxx 方法计算后注入。
"""

import datetime
from typing import Optional

from pydantic import BaseModel


class PatientCreate(BaseModel):
    """创建患者入参（必填：姓名；其余字段均可选）。"""

    name: str                              # 患者姓名（必填）
    gender: Optional[str] = None          # 性别："男"/"女"/"未知"
    birth_date: Optional[datetime.date] = None  # 出生日期（YYYY-MM-DD）
    phone: Optional[str] = None           # 联系电话
    id_card: Optional[str] = None         # 居民身份证号（18位）
    address: Optional[str] = None         # 家庭住址
    # 病案首页扩展字段（住院病历必填）
    ethnicity: Optional[str] = None       # 民族
    marital_status: Optional[str] = None  # 婚姻状况
    occupation: Optional[str] = None      # 职业
    workplace: Optional[str] = None       # 工作单位
    contact_name: Optional[str] = None    # 紧急联系人姓名
    contact_phone: Optional[str] = None   # 紧急联系人电话
    contact_relation: Optional[str] = None# 紧急联系人关系
    blood_type: Optional[str] = None      # 血型


class PatientResponse(BaseModel):
    """患者查询响应（含计算字段 age，不含敏感字段如 id_card）。"""

    id: str
    patient_no: Optional[str] = None  # HIS 系统患者编号（手动录入时为空）
    name: str
    gender: Optional[str] = None
    age: Optional[int] = None         # 当前年龄（由 birth_date 计算，非 DB 字段）
    phone: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    # 是否有进行中的住院接诊 → 前端"在院中"绿色 Tag
    has_active_inpatient: bool = False
    # 是否曾住过院（含已出院），区分"已出院" vs "纯门诊从未住过院"
    has_any_inpatient_history: bool = False

    class Config:
        from_attributes = True  # 允许从 ORM 对象直接实例化


class PatientUpdate(BaseModel):
    """更新患者信息入参（所有字段可选，只更新传入的字段）。"""

    name: Optional[str] = None
    gender: Optional[str] = None
    birth_date: Optional[datetime.date] = None
    phone: Optional[str] = None
    id_card: Optional[str] = None
    address: Optional[str] = None
    ethnicity: Optional[str] = None
    marital_status: Optional[str] = None
    occupation: Optional[str] = None
    workplace: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_relation: Optional[str] = None
    blood_type: Optional[str] = None


class PatientListResponse(BaseModel):
    """患者列表分页响应。

    total : 符合条件的总记录数（用于前端计算总页数）
    items : 当前页的患者数据
    """

    total: int
    items: list[PatientResponse]


class ProfileFieldMeta(BaseModel):
    """档案单个字段的元数据（每个字段独立的"何时确认/谁确认"）。

    - updated_at：医生最近一次写入或主动确认（"✓ 仍准确"）的时间
    - updated_by：医生 ID。前端展示"X 医生 N 天前确认"用
    """

    updated_at: Optional[datetime.datetime] = None
    updated_by: Optional[str] = None


class PatientProfile(BaseModel):
    """患者档案（纵向持久数据，JSONB 重构后）。

    该档案跟随患者而非单次接诊，符合 FHIR 标准：
    AllergyIntolerance / Condition / MedicationStatement 都挂在 Patient 上。

    与原结构相比：
      - 月经史已移除 —— 时变信息，每次接诊在 inquiry_inputs.menstrual_history 重填
      - 新增 fields_meta：每个字段独立 updated_at + updated_by，便于前端展示
        "X 天前确认"以及对时变字段（如长期用药）做过期提醒
      - updated_at 改为各字段最大值的聚合（兼容旧的"档案最后更新于"展示）
    """

    past_history: Optional[str] = None         # 既往史
    allergy_history: Optional[str] = None      # 过敏史
    family_history: Optional[str] = None       # 家族史
    personal_history: Optional[str] = None     # 个人史
    current_medications: Optional[str] = None  # 长期用药（变化稍快，前端 30 天提示）
    marital_history: Optional[str] = None      # 婚育史
    religion_belief: Optional[str] = None      # 宗教信仰
    # 各档案字段最大 updated_at 的聚合；档案完全为空时为 None
    updated_at: Optional[datetime.datetime] = None
    # 字段级元数据（key 是字段名，value 是 ProfileFieldMeta）
    fields_meta: Optional[dict[str, ProfileFieldMeta]] = None


class PatientProfileUpdate(BaseModel):
    """档案更新入参（所有字段可选，只更新传入的字段）。

    传入空字符串 = 显式清空该字段（保留历史更新时间，但 value 为 ""）；
    传入 None = 不修改该字段（保持原值）。月经史已不再属于档案，本 schema 不再接受。
    """

    past_history: Optional[str] = None
    allergy_history: Optional[str] = None
    family_history: Optional[str] = None
    personal_history: Optional[str] = None
    current_medications: Optional[str] = None
    marital_history: Optional[str] = None
    religion_belief: Optional[str] = None


class PatientProfileFieldConfirm(BaseModel):
    """档案"✓ 仍准确"按钮入参：刷新指定字段的 updated_at，不改 value。

    用于 FHIR verificationStatus 思路：医生看了档案确认仍然准确就点这个按钮，
    让"X 天前确认"重新计时。
    """

    field: str  # past_history / allergy_history / ... 之一
