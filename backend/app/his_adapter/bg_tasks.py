"""后台任务引用持有（his_adapter/bg_tasks.py）

2026-08-11 审计延期项修复：多处 fire-and-forget 的 asyncio.create_task 未保存
返回的 Task 引用。asyncio 只持弱引用，任务在完成前可能被 GC 回收并取消，
导致回写等后台动作静默丢失。用模块级强引用集持有，完成后自动移除。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# 强引用集：持有所有在途后台任务，防被 GC 中途取消
_background_tasks: set[asyncio.Task] = set()


def spawn(coro, *, name: str = "") -> asyncio.Task:
    """启动后台任务并持有引用，完成后自动移除；异常只记日志不外抛。"""
    task = asyncio.create_task(coro, name=name or None)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.warning("bg_task.failed: name=%s err=%s", name, exc)

    task.add_done_callback(_done)
    return task
