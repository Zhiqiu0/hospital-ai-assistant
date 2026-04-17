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
