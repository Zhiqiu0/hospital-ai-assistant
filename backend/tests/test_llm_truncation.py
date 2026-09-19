# -*- coding: utf-8 -*-
"""LLM 输出截断分支测试（2026-09-19 补——终检覆盖率盲区次级项）。

守的语义：finish_reason == "length"（被 max_tokens 拦腰砍断）必须抛
**不可重试**的 LLMServiceError——半截 JSON 若被 json.loads 侥幸解析或
上层盲目重试，要么产出残缺病历要么白烧第二次计费。此前该分支零覆盖。
"""
from types import SimpleNamespace

import pytest

from app.services.ai.llm_client import LLMServiceError, llm_client


def _chunk(content=None, finish_reason=None, usage=None):
    choice = SimpleNamespace(delta=SimpleNamespace(content=content),
                             finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


class _FakeStream:
    def __init__(self, chunks):
        self._it = iter(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _patch_stream(monkeypatch, chunks):
    async def _create(**kw):
        return _FakeStream(chunks)

    monkeypatch.setattr(llm_client.client.chat.completions, "create", _create)


@pytest.mark.asyncio
async def test_截断抛不可重试错误(monkeypatch):
    _patch_stream(monkeypatch, [
        _chunk(content='{"issues": ['),
        _chunk(finish_reason="length"),
    ])
    with pytest.raises(LLMServiceError) as ei:
        await llm_client.chat_json_stream([{"role": "user", "content": "x"}])
    assert ei.value.retryable is False, "截断重试大概率再截断，必须标不可重试"
    assert "截断" in str(ei.value)


@pytest.mark.asyncio
async def test_正常结束照常解析(monkeypatch):
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    _patch_stream(monkeypatch, [
        _chunk(content='{"ok"'),
        _chunk(content=': true}', finish_reason="stop", usage=usage),
    ])
    result = await llm_client.chat_json_stream([{"role": "user", "content": "x"}])
    assert result == {"ok": True}
    assert llm_client._last_usage is usage, "usage 要随流带回（token 统计依赖它）"
