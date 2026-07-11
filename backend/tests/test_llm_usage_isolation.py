"""llm_client._last_usage 并发隔离回归

llm_client 是模块级单例。修复前 _last_usage 是实例属性，两个请求并发跑 AI 时
A 的 usage 会被 B 的响应覆盖，导致 token 记账串号（admin 用量统计失真）。
修复：用 ContextVar 承载，按 asyncio 任务隔离——每个请求 task 各持一份，互不干扰。

本用例模拟两个并发 task 各自写入再读回，验证读到的是自己那份而非对方的。
"""
import asyncio

import pytest

from app.services.ai.llm_client import llm_client


@pytest.mark.asyncio
async def test_last_usage_isolated_across_concurrent_tasks():
    async def worker(tag: str, delay: float):
        # 先写自己的 usage，让出事件循环给另一个 task 也写，再读回
        llm_client._last_usage = tag
        await asyncio.sleep(delay)
        return llm_client._last_usage

    a, b = await asyncio.gather(worker("A", 0.02), worker("B", 0.01))
    # 修复前：后写的会覆盖先写的，两个 task 读到同一个值（串号）
    # 修复后：各读各的
    assert a == "A"
    assert b == "B"
