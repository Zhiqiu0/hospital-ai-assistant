"""
接诊相关 Pydantic 模型（schemas/encounter.py）

包含：
  QuickStartRequest  : 一键开始接诊入参（含患者信息和接诊设置）
  EncounterCreate    : 标准创建接诊入参（患者必须已存在）
  InquiryInputUpdate : 保存/更新问诊字段入参（所有字段可选，支持增量保存）
  EncounterResponse  : 接诊记录响应体

字段设计说明：
  QuickStartRequest 包含患者完整信息，因为一键开始接诊时患者可能不存在，
  系统会根据 id_card / (name+phone+birth_date) 查找已有患者，找不到则自动创建。

  InquiryInputUpdate 所有字段为 Optional[str] = None，
  None 表示"不更新此字段"，空字符串""表示"清空此字段"。
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class QuickStartRequest(BaseModel):
    """一键开始接诊请求体（同时创建患者和接诊记录）。

    系统处理逻辑：
      1. 按 id_card 精确查找患者，或按 (name + phone + birth_date) 模糊匹配
      2. 找到则复用，未找到则根据此请求体中的患者字段创建新患者
      3. 创建 Encounter 记录，关联患者和当前医生
    """

    # 患者基本信息
    patient_name: str                      # 患者姓名（必填）
    gender: Optional[str] = "unknown"     # 性别："男"/"女"/"unknown"
    age: Optional[int] = None             # 年龄（用于推算出生年份，精度到年）
    birth_date: Optional[str] = None      # 精确出生日期（YYYY-MM-DD，优先级高于 age）
    id_card: Optional[str] = None         # 身份证号（精确查重用）
    phone: Optional[str] = None
    address: Optional[str] = None
    # 病案首页扩展字段（住院时填写）
    ethnicity: Optional[str] = None
    marital_status: Optional[str] = None
    occupation: Optional[str] = None
    workplace: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_relation: Optional[str] = None
    blood_type: Optional[str] = None
    # 接诊设置
    visit_type: str = "outpatient"        # "outpatient" / "emergency" / "inpatient"
    department_id: Optional[str] = None   # 科室（空则使用当前登录医生的科室）
    bed_no: Optional[str] = None          # 床位号（住院用）
    admission_route: Optional[str] = None  # 入院途径（住院病案首页）
    admission_condition: Optional[str] = None  # 入院病情（住院病案首页）
    # 复诊时前端可直接传入已知的患者 ID，跳过模糊匹配搜索
    patient_id: Optional[str] = None


class EncounterCreate(BaseModel):
    """标准创建接诊记录（患者必须已存在于系统中）。

    与 QuickStartRequest 的区别：
      QuickStartRequest 同时处理患者查找/创建，适合前端一键接诊；
      EncounterCreate 要求 patient_id 已知，适合 HIS 集成场景。
    """

    patient_id: str            # 已存在的患者 UUID
    visit_type: str            # 就诊类型
    department_id: Optional[str] = None
    is_first_visit: bool = True
    bed_no: Optional[str] = None
    admission_route: Optional[str] = None
    admission_condition: Optional[str] = None


class InquiryInputUpdate(BaseModel):
    """保存/更新问诊输入字段（所有字段可选，支持增量保存）。

    值说明：
      None   : 不修改此字段（字段在 DB 中保持原值）
      ""     : 清空此字段
      "文本" : 更新为该文本

    字段分组与 InquiryInput ORM 模型保持一致（见 models/encounter.py）。
    """

    # 基础问诊
    chief_complaint: Optional[str] = None
    history_present_illness: Optional[str] = None
    past_history: Optional[str] = None
    allergy_history: Optional[str] = None
    personal_history: Optional[str] = None
    physical_exam: Optional[str] = None
    initial_impression: Optional[str] = None
    # 住院部扩展字段
    marital_history: Optional[str] = None
    menstrual_history: Optional[str] = None
    family_history: Optional[str] = None
    history_informant: Optional[str] = None
    current_medications: Optional[str] = None
    rehabilitation_assessment: Optional[str] = None
    religion_belief: Optional[str] = None
    pain_assessment: Optional[str] = None
    vte_risk: Optional[str] = None
    nutrition_assessment: Optional[str] = None
    psychology_assessment: Optional[str] = None
    auxiliary_exam: Optional[str] = None
    admission_diagnosis: Optional[str] = None
    # 门诊中医四诊
    tcm_inspection: Optional[str] = None
    tcm_auscultation: Optional[str] = None
    tongue_coating: Optional[str] = None
    pulse_condition: Optional[str] = None
    # 门诊诊断细化
    western_diagnosis: Optional[str] = None
    tcm_disease_diagnosis: Optional[str] = None
    tcm_syndrome_diagnosis: Optional[str] = None
    # 治疗意见
    treatment_method: Optional[str] = None
    treatment_plan: Optional[str] = None
    followup_advice: Optional[str] = None
    precautions: Optional[str] = None
    # 急诊附加
    observation_notes: Optional[str] = None
    patient_disposition: Optional[str] = None
    # 时间
    visit_time: Optional[str] = None
    onset_time: Optional[str] = None


class EncounterResponse(BaseModel):
    """接诊记录响应体（返回给前端的接诊基本信息）。"""

    id: str
    patient_id: str
    visit_type: str
    status: str         # "in_progress" / "completed" / "cancelled"
    is_first_visit: bool
    visited_at: datetime
    department_id: Optional[str] = None

    class Config:
        from_attributes = True
