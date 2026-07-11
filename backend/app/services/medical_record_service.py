"""病历服务门面（app/services/medical_record_service.py）

职责：把病历相关能力按职责拆到多个 mixin，对外仍暴露单一 MedicalRecordService。
调用方零改动（`MedicalRecordService(db).xxx()` 用法完全不变）。

拆分（Round 5: 超标文件拆分，657 行 → 门面 + 4 mixin）：
  - _medical_record_crud.MedicalRecordCrudMixin   : 新建占位 / 按 ID 查 / 医生编辑保存 / 版本列表
  - _medical_record_draft.MedicalRecordDraftMixin : auto-save 草稿 + AI 草稿保存（不签发）
  - _medical_record_sign.MedicalRecordSignMixin   : quick_save 签发（含病案首页快照 + 关闭接诊）
  - _medical_record_query.MedicalRecordQueryMixin : 分页查询共用逻辑 + 按医生/按患者列表

版本控制设计：
  每次保存内容都会创建一条新 RecordVersion 记录，并递增 MedicalRecord.current_version。
  版本号单调递增，不可逆——即使回滚到旧内容，也会生成新版本号，确保完整审计链。

签发（quick_save）设计：
  签发 = 医生确认本次接诊处理完毕。签发后：
    1. MedicalRecord.status 设为 'submitted'，防止继续编辑
    2. Encounter.status 设为 'completed'，从进行中列表移除
  内容以 {"text": "..."} 格式存储（quick_save 模式），与结构化格式（各字段分开）并存，
  读取时由 encounter_service 统一做格式兼容处理。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.services._medical_record_crud import MedicalRecordCrudMixin
from app.services._medical_record_draft import MedicalRecordDraftMixin
from app.services._medical_record_query import MedicalRecordQueryMixin
from app.services._medical_record_sign import MedicalRecordSignMixin


class MedicalRecordService(
    MedicalRecordCrudMixin,
    MedicalRecordDraftMixin,
    MedicalRecordSignMixin,
    MedicalRecordQueryMixin,
):
    """病历数据访问服务，封装病历 CRUD 及版本控制逻辑。

    具体方法实现分布在上面 4 个 mixin 中，本类只负责组合 + 持有 db session。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
