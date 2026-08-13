"""HIS 对接的数据传输对象（DTO）

不是 SQLAlchemy ORM model（那些复用现有 encounter / medical_record 表，
仅扩展一个 his_external_ref JSONB 字段记录 HIS 标识）。

本文件定义：
  - HISExternalRef    : HIS 患者/就诊标识（存进 encounter.his_external_ref 的 JSONB 结构文档）
  - ApiEnvelope / AdmitPushRequest : HIS 外部接口（接诊推送/回写）用的信封与入参

注：控件模式的 Fill* / DesktopHeartbeat DTO 已随 UI 自动化方案退休删除；
    旧 embed 会话的 StartEmbedRequest/StartEmbedResponse 已随 /embed 入口下线删除
    （2026-08-12，接入统一走接诊推送 + 叫号工作台）。

设计原则：
  - 强类型 + Pydantic 校验，前后端契约清晰
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class HISExternalRef(BaseModel):
    """HIS 患者/就诊外部标识，存进 encounter.his_external_ref JSONB 字段。

    为什么不另开 his_sessions 表：
      嵌入会话本质上就是一次"接诊"——患者来诊、医生录入、生成病历、签发。
      跟普通 SaaS 接诊唯一差异是"病历最终去向是 HIS"而不是"自己的归档"。
      复用 encounter + medical_record 表能让 AI 生成 / 质控 / 审计 / 历史
      查询所有现有逻辑零改动直接复用。

    JSONB 而不是分散的列：
      不同 HIS 厂商的标识字段不一样（金算盘是 patient_no/visit_no，
      东软可能是别的命名），用 JSONB 灵活适配，避免每接一家新医院加新列。
    """

    his_brand: str = Field(..., description="HIS 厂商，如 'jinsuanpan' / 'donghua'")
    hospital_code: str = Field(..., description="医院国家编码，如 H33052300957")
    his_patient_no: str = Field(..., description="HIS 患者编号，跨就诊稳定")
    his_visit_no: Optional[str] = Field(None, description="HIS 就诊号，单次就诊维度")
    his_doctor_no: Optional[str] = Field(None, description="HIS 医生工号（可选）")


class ApiEnvelope(BaseModel):
    """HIS 对接统一响应信封：{code, message, trace_id, data}。"""

    code: int = 0
    message: str = "success"
    trace_id: str = ""
    data: dict = Field(default_factory=dict)


def ok(data: Optional[dict] = None, trace_id: str = "") -> ApiEnvelope:
    """成功信封。"""
    return ApiEnvelope(code=0, message="success", trace_id=trace_id, data=data or {})


def err(code: int, message: str, trace_id: str = "") -> ApiEnvelope:
    """失败信封（HTTP 仍 200，靠 code 区分）。"""
    return ApiEnvelope(code=code, message=message, trace_id=trace_id, data={})


class AdmitVitals(BaseModel):
    """接诊推送里的选填体征（规范 3.1 vitals.*，与 3.2 回写字段对称）。

    这些是 HIS 侧护士/设备**实测**的真实值，不是 AI 推断——预填进工作台既省去
    医生重复录入，也不违反"AI 不得编造数值"的红线（红线针对的是无出处的数值）。
    全部按字符串收（厂商可能给 "36.5"/"36.5℃"/空串），落库前统一清洗。
    """

    temperature: Optional[str] = None    # 体温 ℃
    pulse: Optional[str] = None          # 脉搏 次/分
    respiration: Optional[str] = None    # 呼吸 次/分
    bp_systolic: Optional[str] = None    # 收缩压 mmHg
    bp_diastolic: Optional[str] = None   # 舒张压 mmHg
    spo2: Optional[str] = None           # 血氧饱和度 %
    height: Optional[str] = None         # 身高 cm
    weight: Optional[str] = None         # 体重 kg


class AdmitPushRequest(BaseModel):
    """接诊推送请求体（HIS→我方）。visit_id/hospital_code/patient_name 必填，其余容错可空。"""

    visit_id: str
    hospital_code: str
    patient_name: str
    gender: Literal["male", "female", "unknown"] = "unknown"
    birth_date: Optional[str] = None
    id_card: Optional[str] = None
    phone: Optional[str] = None
    dept_code: Optional[str] = None
    dept_name: Optional[str] = None
    doctor_code: Optional[str] = None
    doctor_name: Optional[str] = None
    visit_type: Optional[str] = None
    is_first_visit: Optional[bool] = None
    agent_device_ip: Optional[str] = None
    agent_device_mac: Optional[str] = None
    # ── 选填档案/体征（规范 3.1，"有则推送"）──────────────────────────────
    # 2026-08-13 补接：规范与发给厂商的参考实现都带这些字段，后端却没定义，
    # pydantic 默认忽略未知字段 → 厂商推来的体温血压被**静默丢弃**，联调现场
    # 会变成"我推了/我没收到"且日志无痕。
    vitals: Optional[AdmitVitals] = None
    allergy_history: Optional[str] = None   # 过敏史（纵向档案，跟随患者）
    past_history: Optional[str] = None      # 既往史（同上）
