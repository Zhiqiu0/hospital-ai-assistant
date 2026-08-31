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


# 延迟第二次删除的等待秒数（2026-08-31 并发矩阵审计）：
# cache-aside 的经典回填竞态——读请求 miss 后 SELECT 到旧值，写请求在这中间
# 提交并失效缓存，读请求这才 set_json 把**旧值**以 300s TTL 写回。此后 5 分钟
# 全院读到旧过敏史，而失效动作已经执行过、没有第二次纠正机会。
# 过敏史是开药前飘红警示的字段，值得多删一次。1 秒相对于"SELECT 到 set_json"
# 这段窗口（同进程微秒级、跨进程毫秒级）足够宽裕。
_DELAYED_INVALIDATE_SECONDS = 1.0


async def _delete_patient_keys(patient_id: str) -> None:
    """删患者两个缓存键 + 搜索缓存前缀。"""
    await redis_cache.delete(
        _BASIC_KEY.format(pid=patient_id),
        _PROFILE_KEY.format(pid=patient_id),
    )
    # 患者基本信息变更也会影响搜索结果，把搜索缓存全清掉
    await redis_cache.delete_prefix("patient:search:")


async def _delayed_reinvalidate(patient_id: str) -> None:
    """延迟再删一次（见 _DELAYED_INVALIDATE_SECONDS 说明）。失败不影响主流程。"""
    import asyncio
    import logging

    try:
        await asyncio.sleep(_DELAYED_INVALIDATE_SECONDS)
        await _delete_patient_keys(patient_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logging.getLogger(__name__).warning(
            "patient_cache.delayed_invalidate: 二次失效失败 pid=%s", patient_id
        )


async def _invalidate_patient_cache(patient_id: str) -> None:
    """患者写操作（update / update_profile）后失效缓存。

    双删：立即删一次 + 延迟 1 秒再删一次，堵住并发读把旧值回填的窗口。
    """
    await _delete_patient_keys(patient_id)
    # 后台延迟二次删除；用 bg_tasks.spawn 持引用防 GC 中途取消
    from app.his_adapter.bg_tasks import spawn

    spawn(_delayed_reinvalidate(patient_id), name=f"patient_cache_reinval:{patient_id}")
