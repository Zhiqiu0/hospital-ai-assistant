"""ai_tasks 记录真实模型名的回归测试（2026-08-14 第七轮审计 #7）。

原实现 log_ai_task 写死 model_name=llm_client.model（全局默认），而调用它的
追问/检查建议、病历生成、质控**恰恰是可以按场景配模型的那几个**。
于是管理员把质控换成别的模型后，ai_tasks 里每条仍记着默认模型：
成本归集算错、"换模型后效果变化"没法回溯、排查线上问题时看到的模型是假的。
"""

import pytest
from sqlalchemy import select

from app.models.medical_record import AITask
from app.services.ai.task_logger import log_ai_task


@pytest.mark.asyncio
async def test_传入的模型名被如实记录(monkeypatch, async_db):
    from app.database import AsyncSessionLocal
    import app.services.ai.task_logger as tl

    # log_ai_task 用独立会话，测试里换成当前测试会话
    class _Ctx:
        async def __aenter__(self):
            return async_db

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(tl, "AsyncSessionLocal", lambda: _Ctx())
    # commit 会结束测试事务，这里替换成 flush
    monkeypatch.setattr(async_db, "commit", async_db.flush)

    await log_ai_task("qc", model_name="deepseek-reasoner", prompt_version="v3")

    task = (await async_db.execute(select(AITask))).scalars().first()
    assert task is not None
    assert task.model_name == "deepseek-reasoner", "记的不是实际用的模型"
    assert task.prompt_version == "v3"


@pytest.mark.asyncio
async def test_不传时回落全局默认(monkeypatch, async_db):
    import app.services.ai.task_logger as tl
    from app.services.ai.llm_client import llm_client

    class _Ctx:
        async def __aenter__(self):
            return async_db

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(tl, "AsyncSessionLocal", lambda: _Ctx())
    monkeypatch.setattr(async_db, "commit", async_db.flush)

    await log_ai_task("generate")

    task = (await async_db.execute(select(AITask))).scalars().first()
    assert task.model_name == llm_client.model
    assert task.prompt_version is None
