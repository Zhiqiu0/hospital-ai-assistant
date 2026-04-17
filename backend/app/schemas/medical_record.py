"""
病历相关 Pydantic 模型（schemas/medical_record.py）

包含：
  QuickSaveRequest      : 出具最终病历时快速保存的入参
  MedicalRecordCreate   : 创建病历记录的入参
  RecordGenerateRequest : 通过问诊数据生成病历的入参
  RecordContinueRequest : 续写病历的入参
  RecordPolishRequest   : 润色病历的入参
  RecordContentUpdate   : 更新病历内容的入参
  MedicalRecordResponse : 病历记录查询响应
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class QuickSaveRequest(BaseModel):
    """出具最终病历时快速保存的入参。

    前端在用户点击「出具最终病历」时调用，
    将编辑区的完整文本内容保存到 DB 并锁定病历状态。
    """

    encounter_id: str         # 关联接诊 ID
    record_type: str = "outpatient"  # 病历类型
    content: str              # 病历全文（markdown 格式）


class MedicalRecordCreate(BaseModel):
    """创建病历主记录的入参（在病历生成之前先创建主记录）。"""

    encounter_id: str
    record_type: str


class RecordGenerateRequest(BaseModel):
    """通过问诊数据生成病历草稿的入参。

    inquiry_input 是包含所有问诊字段的字典，
    格式与 InquiryInputUpdate 字段名一致。
    """

    inquiry_input: dict  # 问诊字段字典，key=字段名，value=内容文本


class RecordContinueRequest(BaseModel):
    """续写病历（在已有内容基础上继续生成）的入参。"""

    current_content: dict  # 当前已有内容
    target_field: str      # 要续写的目标字段名


class RecordPolishRequest(BaseModel):
    """润色病历内容的入参。

    content 是包含病历各字段的字典。
    target_fields 为空时全字段润色，指定时只润色选中字段。
    """

    content: dict
    target_fields: Optional[list[str]] = None  # 要润色的字段列表（None=全部润色）


class RecordContentUpdate(BaseModel):
    """手动更新病历内容的入参（医生直接编辑后保存）。"""

    content: dict  # 更新后的病历字段内容


class MedicalRecordResponse(BaseModel):
    """病历主记录查询响应。"""

    id: str
    encounter_id: str
    record_type: str
    status: str           # "draft"（草稿）/ "final"（已出具）
    current_version: int  # 当前最新版本号
    created_at: datetime

    class Config:
        from_attributes = True
