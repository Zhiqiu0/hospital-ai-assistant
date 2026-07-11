"""患者相关 Redis 缓存键与失效函数（services/patient_cache.py）

从 patient_service 拆出（Round: 超标文件拆分）。放到独立底层模块，
让各 mixin 与外部调用方（encounters 路由 / _encounter_* mixin）都能直接
import `_invalidate_patient_cache`，无需绕回 PatientService 实例，也避免
mixin 之间的循环导入。

patient_service.py 会 re-export `_invalidate_patient_cache`，保持原有导入路径不变：
    from app.services.patient_service import _invalidate_patient_cache
"""
from app.services.redis_cache import redis_cache

# Redis 缓存 key：基本信息和档案分开缓存，避免一改 profile 把基本信息也失效
_BASIC_KEY = "patient:basic:{pid}"
_PROFILE_KEY = "patient:profile:{pid}"
_BASIC_TTL = 300   # 5 分钟，基本信息变动很少
_PROFILE_TTL = 300


async def _invalidate_patient_cache(patient_id: str) -> None:
    """患者写操作（update / update_profile）后失效缓存。"""
    await redis_cache.delete(
        _BASIC_KEY.format(pid=patient_id),
        _PROFILE_KEY.format(pid=patient_id),
    )
    # 患者基本信息变更也会影响搜索结果，把搜索缓存全清掉
    await redis_cache.delete_prefix("patient:search:")
