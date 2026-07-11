"""接诊相关 Redis 缓存键与失效函数（services/encounter_cache.py）

从 encounter_service 拆出（Round: 超标文件拆分）。放到独立底层模块，
让各 service（medical_record / voice / inpatient / admin_record）能直接 import
失效函数，无需绕回 EncounterService 实例，也避免与 mixin 之间的循环导入。

encounter_service.py 会 re-export invalidate_* 两个函数，保持原有导入路径不变：
    from app.services.encounter_service import invalidate_encounter_snapshot
"""
from app.services.redis_cache import redis_cache

# 工作台快照缓存（snapshot 是 5+ 张表关联，是工作台启动热路径）
_SNAPSHOT_KEY = "encounter:snapshot:{eid}"
_SNAPSHOT_TTL = 60  # 60 秒，保存任意子数据时主动失效
# "我的进行中接诊列表"缓存
_MY_ENCOUNTERS_KEY = "encounter:my:{doctor_id}"
_MY_ENCOUNTERS_TTL = 30


async def invalidate_encounter_snapshot(encounter_id: str) -> None:
    """保存 inquiry / 病历版本 / 语音 / 接诊状态变化后调用，失效 snapshot 缓存。"""
    await redis_cache.delete(_SNAPSHOT_KEY.format(eid=encounter_id))


async def invalidate_my_encounters(doctor_id: str) -> None:
    """新建/关闭接诊后调用，失效"我的进行中接诊列表"缓存。"""
    await redis_cache.delete(_MY_ENCOUNTERS_KEY.format(doctor_id=doctor_id))
