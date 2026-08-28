# -*- coding: utf-8 -*-
"""ai_tasks 载荷瘦身口径测试（2026-08-28 全量体检·保留期机制）。

锁死契约：超期行只清 input_snapshot/output_result 两个大字段，
行本身与 token 统计元数据必须原样保留（成本统计口径不变）；
期内行完全不动。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import or_, select, update

from app.models.medical_record import AITask


@pytest.mark.asyncio
async def test_payload_slimming_caliber(async_db):
    old = AITask(task_type="generate", status="done",
                 input_snapshot={"p": "旧输入"}, output_result={"r": "旧输出"},
                 token_input=100, token_output=200,
                 created_at=datetime.now() - timedelta(days=200))
    new = AITask(task_type="qc", status="done",
                 input_snapshot={"p": "新输入"}, output_result={"r": "新输出"},
                 token_input=50, token_output=60,
                 created_at=datetime.now() - timedelta(days=10))
    async_db.add_all([old, new])
    await async_db.commit()
    old_id, new_id = old.id, new.id

    # 与 scripts/cleanup_ai_task_payloads.py 同款 UPDATE（脚本走生产
    # AsyncSessionLocal，测试库无法直接调脚本入口，这里锁的是同一条 SQL 口径）
    cutoff = datetime.now() - timedelta(days=180)
    cond = (AITask.created_at < cutoff,
            or_(AITask.input_snapshot.isnot(None), AITask.output_result.isnot(None)))
    await async_db.execute(
        update(AITask).where(*cond).values(input_snapshot=None, output_result=None))
    await async_db.commit()

    o = (await async_db.execute(select(AITask).where(AITask.id == old_id))).scalar_one()
    n = (await async_db.execute(select(AITask).where(AITask.id == new_id))).scalar_one()
    assert o.input_snapshot is None and o.output_result is None, "超期载荷应清空"
    assert o.token_input == 100 and o.token_output == 200 and o.status == "done", \
        "行与统计元数据必须保留"
    assert n.input_snapshot == {"p": "新输入"} and n.output_result == {"r": "新输出"}, \
        "期内行完全不动"
