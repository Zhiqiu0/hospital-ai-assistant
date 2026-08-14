"""
病历相关 Pydantic 模型（schemas/medical_record.py）

包含：
  QuickSaveRequest      : 出具最终病历时快速保存的入参
  MedicalRecordCreate   : 创建病历记录的入参
  RecordContentUpdate   : 更新病历内容的入参
  MedicalRecordResponse : 病历记录查询响应

历史说明（2026-08-12 清理）：旧范式 AI 路由的三个入参
（RecordGenerateRequest/RecordContinueRequest/RecordPolishRequest）
已随路由一起删除，AI 生成统一走 /ai/quick-* 系列（schemas 见 ai_generation 路由内联模型）。
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


class RecordContentUpdate(BaseModel):
    """手动更新病历内容的入参（医生直接编辑后保存）。"""

    content: dict  # 更新后的病历字段内容


class AutoSaveDraftRequest(BaseModel):
    """编辑器 auto-save 入参（5 秒防抖触发）。

    与 RecordContentUpdate 区别：
      - 走 auto_save_draft service（不爆版本，UPSERT 当前 version 的 content）
      - 用 (encounter_id, record_type) 而非 record_id 定位——首次还没 record_id
      - 含可选 expected_updated_at 做乐观锁，多设备冲突保护
    """

    encounter_id: str
    record_type: str
    content: str  # 完整病历正文（前端编辑器当前值）
    expected_updated_at: Optional[datetime] = None  # 上次保存返回的 updated_at，乐观锁凭证
    # 记录时间（临床相关时点）。住院文书用它表达"这份病程记的是哪天的事"；
    # 门急诊当场书写不必传。与系统录入时间差得多会被标为补记，
    # 不是可以随意改的时间线 —— 规范依据见 services/record_time.py。
    recorded_at: Optional[datetime] = None


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


class RecordExportAudit(BaseModel):
    """病历导出/打印的审计上报入参（2026-08-14 第六轮审计修复）。

    打印与导出全在客户端完成，服务端无从感知，而导出是把整份病历连同患者身份
    信息一起带走——放开归属校验后审计是唯一追责手段，这条路径不能没有留痕。
    字段都可空：上报失败不该阻断医生导出，能记多少记多少。
    """

    record_id: Optional[str] = None
    encounter_id: Optional[str] = None
    record_type: Optional[str] = None
    method: str = "print"          # print / word
    is_signed: bool = False
