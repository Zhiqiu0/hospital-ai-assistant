"""最终正文诊断核对合同：客户端只确认名称/类别/主诊断，编码始终由后端决定。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

DiagnosisCategory = Literal["western", "tcm_disease", "tcm_syndrome"]


class ConfirmedDiagnosis(BaseModel):
    """只允许显式确认字段，拒绝code等额外属性及字符串/整数冒充布尔值。"""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=2000)
    category: DiagnosisCategory | None = None
    is_primary: StrictBool


class DiagnosisPreviewRequest(BaseModel):
    """无接诊quickstart也可仅解析正文；修订用record_id定位历史编码依据。"""
    encounter_id: str | None = None
    record_id: str | None = None
    record_type: str
    content: str = Field(max_length=500_000)

    @field_validator("record_type")
    @classmethod
    def valid_record_type(cls, value):
        """复用病历类型枚举，延迟导入避免提交schema之间循环依赖。"""
        from app.schemas.medical_record import _validate_record_type
        return _validate_record_type(value)


class DiagnosisPreviewItem(BaseModel):
    """精确匹配的编码仅供展示；没有依据就返回null，不猜测医学类别。"""
    name: str
    category: DiagnosisCategory | None = None
    is_primary: bool = False
    code: str | None = None
    code_type: str | None = None


class DiagnosisPreviewResponse(BaseModel):
    """格式错误独立于待确认主诊断；前端按HIS标识区分回写和纯本地签发。"""
    diagnoses: list[DiagnosisPreviewItem]
    requires_confirmation: bool
    projection_error: str | None
    his_writeback_required: bool
