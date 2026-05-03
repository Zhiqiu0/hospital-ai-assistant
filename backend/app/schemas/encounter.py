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
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


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
    # 出生日期（YYYY-MM-DD）；前端展示年龄时用 dayjs().diff(birth_date, 'year') 计算，
    # 不再接受 age 字段，避免推算导致出生日期被劣化为"当年 1 月 1 日"。
    birth_date: Optional[str] = None
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
    # 生命体征（结构化独立字段，不再混入 physical_exam 文本）
    temperature: Optional[str] = None     # 体温 ℃
    pulse: Optional[str] = None            # 脉搏 次/分
    respiration: Optional[str] = None      # 呼吸 次/分
    bp_systolic: Optional[str] = None      # 血压 收缩压 mmHg
    bp_diastolic: Optional[str] = None     # 血压 舒张压 mmHg
    spo2: Optional[str] = None             # 血氧饱和度 %
    height: Optional[str] = None           # 身高 cm
    weight: Optional[str] = None           # 体重 kg
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


class EncounterCancelRequest(BaseModel):
    """取消接诊请求体（POST /encounters/{id}/cancel）。

    业务规则：
      - 仅主治医生（doctor_id == current_user.id）可取消
      - 接诊状态必须是 in_progress（已 completed/cancelled 直接幂等返回）
      - 已签发病历的接诊不可取消（要走病历作废流程，Phase 1 不做）
      - 取消后 status='cancelled'，所有关联数据（inquiry/voice/AI 草稿/病历草稿）保留供回溯

    cancel_reason 设计：
      最小 1 字符，最大 500，前端预设 5 选 + 自由备注
      预设："误开接诊" / "患者未到诊" / "患者已转院" / "重复创建" / "其他"
      "其他"时备注必填（前端 UI 校验，后端不强制——后端只确保非空字符串）
    """

    cancel_reason: str = Field(min_length=1, max_length=500)


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


class InquirySnapshot(BaseModel):
    """工作台快照里的问诊数据序列化结构。

    与 InquiryInput ORM 字段一一对应；用 Pydantic 自动把 None → ""，
    取代原 service 里 40+ 行手工 `or ""` 拼装。
    """

    model_config = {"from_attributes": True}

    # 基础问诊
    chief_complaint: str = ""
    history_present_illness: str = ""
    past_history: str = ""
    allergy_history: str = ""
    personal_history: str = ""
    physical_exam: str = ""
    initial_impression: str = ""
    # 生命体征
    temperature: str = ""
    pulse: str = ""
    respiration: str = ""
    bp_systolic: str = ""
    bp_diastolic: str = ""
    spo2: str = ""
    height: str = ""
    weight: str = ""
    # 住院扩展
    marital_history: str = ""
    menstrual_history: str = ""
    family_history: str = ""
    history_informant: str = ""
    current_medications: str = ""
    rehabilitation_assessment: str = ""
    religion_belief: str = ""
    pain_assessment: str = ""
    vte_risk: str = ""
    nutrition_assessment: str = ""
    psychology_assessment: str = ""
    auxiliary_exam: str = ""
    admission_diagnosis: str = ""
    # 中医四诊
    tcm_inspection: str = ""
    tcm_auscultation: str = ""
    tongue_coating: str = ""
    pulse_condition: str = ""
    # 门诊诊断细化
    western_diagnosis: str = ""
    tcm_disease_diagnosis: str = ""
    tcm_syndrome_diagnosis: str = ""
    # 治疗意见
    treatment_method: str = ""
    treatment_plan: str = ""
    followup_advice: str = ""
    precautions: str = ""
    # 急诊附加
    observation_notes: str = ""
    patient_disposition: str = ""
    # 时间
    visit_time: str = ""
    onset_time: str = ""
    # 版本号（与 ORM 同名透传）
    version: int = 1

    @model_validator(mode="before")
    @classmethod
    def _normalize_none_to_empty(cls, data: Any) -> Any:
        """ORM 字段大量 Optional[str]；进入 schema 前把 None 统一替换为 ""，
        避免每个字段都写 BeforeValidator。
        """
        if isinstance(data, dict):
            return {k: ("" if v is None and k != "version" else v) for k, v in data.items()}
        # 来自 ORM（from_attributes=True）：取 cls 模型字段，逐个读属性并把 None 替换
        result = {}
        for field in cls.model_fields:
            value = getattr(data, field, None)
            if value is None and field != "version":
                value = ""
            if value is None and field == "version":
                value = 1
            result[field] = value
        return result
