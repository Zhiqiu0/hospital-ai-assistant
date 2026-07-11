"""接诊服务门面（services/encounter_service.py）

职责：把接诊相关能力按职责拆到多个 mixin，对外仍暴露单一 EncounterService。
调用方零改动（`EncounterService(db).xxx()` 用法完全不变）。

拆分（Round: 超标文件拆分，732 行 → 门面 + 4 mixin + cache + serializers）：
  - _encounter_lifecycle.EncounterLifecycleMixin : 新建 / 查重 / 我的接诊 / 按 ID 查
  - _encounter_cancel.EncounterCancelMixin       : 取消接诊 + 孤儿患者软删
  - _encounter_snapshot.EncounterSnapshotMixin   : 工作台快照组装（患者/问诊/病历/语音/AI 产物）
  - _encounter_inquiry.EncounterInquiryMixin     : 问诊保存 + 同步上次病历
  - encounter_cache                              : Redis 键与失效函数
  - encounter_serializers                        : ORM→dict 纯函数

兼容：invalidate_encounter_snapshot / invalidate_my_encounters 从本模块 re-export，
其它 service/路由的 `from app.services.encounter_service import invalidate_*` 保持可用。
"""
from sqlalchemy.ext.asyncio import AsyncSession

# re-export：保持既有导入路径（ai_voice / medical_record_service / admin_record_service / encounters 路由都在用）
from app.services.encounter_cache import (  # noqa: F401
    invalidate_encounter_snapshot,
    invalidate_my_encounters,
)
from app.services._encounter_cancel import EncounterCancelMixin
from app.services._encounter_inquiry import EncounterInquiryMixin
from app.services._encounter_lifecycle import EncounterLifecycleMixin
from app.services._encounter_snapshot import EncounterSnapshotMixin


class EncounterService(
    EncounterLifecycleMixin,
    EncounterCancelMixin,
    EncounterSnapshotMixin,
    EncounterInquiryMixin,
):
    """接诊服务：接诊记录的创建、查询、取消和工作台数据组装。

    具体方法实现分布在上面 4 个 mixin 中，本类只负责组合 + 持有 db session。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
