"""HIS 对接的数据传输对象（DTO）

不是 SQLAlchemy ORM model（那些复用现有 encounter / medical_record 表，
仅扩展一个 his_external_ref JSONB 字段记录 HIS 标识）。

本文件定义：
  - HISExternalRef    : 嵌入会话关联的 HIS 患者/就诊标识（存进 encounter.his_external_ref）
  - StartEmbedRequest : 桌面 Agent → 后端 /embed/start 入参
  - StartEmbedResponse: 后端返回给 Agent 的会话 token + URL
  - FillField         : 单个字段的填入指令
  - DesktopHeartbeat  : Agent 心跳上报数据

设计原则：
  - 强类型 + Pydantic 校验，前后端契约清晰
  - 字段命名跟 jinsuanpan_map.yaml 对齐，方便排查
"""

from datetime import datetime
from typing import Any, Literal, Optional

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


class StartEmbedRequest(BaseModel):
    """桌面 Agent 启动嵌入会话的请求体。

    Agent 在医生触发 AI 助手时从 HIS 当前界面读取以下信息，POST 给后端，
    后端创建会话 + 签发 token 给浏览器嵌入页用。
    """

    his_ref: HISExternalRef = Field(..., description="HIS 患者标识")
    # 患者基础信息（用于 AI 上下文，不持久化到 patients 表，只放 encounter）
    patient_name: str
    patient_gender: Optional[Literal["male", "female", "unknown"]] = "unknown"
    patient_birth_date: Optional[str] = Field(None, description="ISO 日期 YYYY-MM-DD")
    # Agent 自身信息（审计用）
    agent_device_id: str = Field(..., description="桌面 Agent 设备 ID")
    agent_version: str = Field(..., description="桌面 Agent 版本号")


class StartEmbedResponse(BaseModel):
    """后端响应给 Agent 的会话结果。"""

    encounter_id: str
    embed_token: str = Field(..., description="JWT，4h 有效，浏览器嵌入页跳过登录用")
    embed_url: str = Field(..., description="带 token 和 patient context 的完整 URL")
    expires_at: datetime


class FillField(BaseModel):
    """单个字段填入指令（Agent /fill 接口接收）。"""

    section: Literal["intake", "record", "diagnosis"] = Field(
        ..., description="字段属于哪个区块"
    )
    field_key: str = Field(..., description="MediScribe 字段名，如 'chief_complaint'")
    value: Any = Field(..., description="字段值，字符串/数值/列表均可")


class FillRequest(BaseModel):
    """嵌入页 → 桌面 Agent /fill 的整体填入请求。"""

    encounter_id: str
    fields: list[FillField]


class FillFieldResult(BaseModel):
    """单个字段填入结果（用于进度上报和审计）。"""

    field_key: str
    his_automation_id: Optional[str] = None
    status: Literal["success", "failed", "skipped", "fallback_clipboard"]
    duration_ms: int = 0
    error_message: Optional[str] = None


class FillResult(BaseModel):
    """整体填入结果。"""

    status: Literal["success", "partial", "failed"]
    encounter_id: str
    total_fields: int
    succeeded: int
    failed: int
    duration_ms: int
    field_results: list[FillFieldResult]


class DesktopHeartbeat(BaseModel):
    """桌面 Agent 心跳上报。"""

    agent_device_id: str
    agent_version: str
    doctor_id: Optional[str] = None  # Agent 启动后医生登录的 MediScribe 账号
    his_detected: bool = False
    his_brand: Optional[str] = None
