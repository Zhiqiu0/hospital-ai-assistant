"""患者服务门面（services/patient_service.py）

职责：把患者档案能力按职责拆到多个 mixin，对外仍暴露单一 PatientService。
调用方零改动（`PatientService(db).xxx()` 用法完全不变）。

拆分（Round: 超标文件拆分，653 行 → 门面 + 4 mixin + cache + validators）：
  - _patient_common.PatientCommonMixin   : 共享读辅助（ORM→dict / 批量住院状态）
  - _patient_query.PatientQueryMixin     : 查重 / 分页搜索 / 按 ID 单查
  - _patient_write.PatientWriteMixin      : 新建建档（含身份证查重）/ 更新基本信息
  - _patient_profile.PatientProfileMixin  : 患者档案（JSONB 纵向数据）读写 + 字段确认
  - patient_cache                         : Redis 键与失效函数
  - _patient_validators                   : 跨字段校验纯函数

兼容 re-export（保持既有导入路径不变）：
  - `_invalidate_patient_cache`            : encounters 路由 / _encounter_* mixin 在用
  - `_assert_id_card_birth_date_consistent`: test_validators_identity.py 在用
"""
from sqlalchemy.ext.asyncio import AsyncSession

# re-export：保持既有导入路径（encounters 路由 / _encounter_cancel / _encounter_lifecycle 都在用）
from app.services.patient_cache import _invalidate_patient_cache  # noqa: F401
from app.services._patient_validators import (  # noqa: F401
    _assert_id_card_birth_date_consistent,
)
from app.services._patient_common import PatientCommonMixin
from app.services._patient_profile import PatientProfileMixin
from app.services._patient_query import PatientQueryMixin
from app.services._patient_write import PatientWriteMixin


class PatientService(
    PatientCommonMixin,
    PatientQueryMixin,
    PatientWriteMixin,
    PatientProfileMixin,
):
    """患者数据访问服务，封装患者 CRUD 及去重逻辑。

    具体方法实现分布在上面 4 个 mixin 中，本类只负责组合 + 持有 db session。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
