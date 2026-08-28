# -*- coding: utf-8 -*-
"""LLM 故障业务化测试（2026-08-28 全量体检：欠费可识别）。

覆盖：
  - 状态码→中文文案/可重试标记 的映射（402 欠费必须不可重试且文案指向管理员）
  - 生成重试循环对不可重试异常立即上抛（不白烧第二次计费）
  - qc-fix 失败回退必须带 degraded 标记（不再静默把建议原文冒充 AI 修复）
"""
import httpx
import pytest
from openai import APIStatusError, APITimeoutError

from app.schemas.ai_request import QCFixRequest
from app.services.ai._qc_ops import run_qc_fix
from app.services.ai.llm_client import LLMServiceError, _classify_llm_error
from app.services.ai.record_gen_v2_service import _call_llm_json_with_retry


def _status_error(code: int) -> APIStatusError:
    """构造带指定状态码的 openai SDK 异常。"""
    req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    resp = httpx.Response(code, request=req, json={"error": {"message": "x"}})
    return APIStatusError("err", response=resp, body=None)


def test_classify_402_non_retryable_with_admin_message():
    err = _classify_llm_error(_status_error(402))
    assert err.retryable is False
    assert "余额不足" in err.user_message and "管理员" in err.user_message


def test_classify_matrix():
    assert _classify_llm_error(_status_error(401)).retryable is False
    assert _classify_llm_error(_status_error(429)).retryable is True
    assert _classify_llm_error(_status_error(503)).retryable is True
    assert _classify_llm_error(APITimeoutError(request=None)).retryable is True
    # 未知异常兜底为可重试通用失败
    assert _classify_llm_error(RuntimeError("x")).retryable is True


@pytest.mark.asyncio
async def test_retry_loop_skips_non_retryable(monkeypatch):
    """欠费类确定性失败必须只调 1 次上游，不做注定失败的二次计费。"""
    calls = {"n": 0}

    async def fake_stream(*a, **k):
        calls["n"] += 1
        raise LLMServiceError("AI 账户余额不足", retryable=False, status_code=402)

    from app.services.ai import record_gen_v2_service as m
    monkeypatch.setattr(m.llm_client, "chat_json_stream", fake_stream)
    with pytest.raises(LLMServiceError):
        await _call_llm_json_with_retry("p", {
            "temperature": 0.3, "max_tokens": 100, "model_name": "m"})
    assert calls["n"] == 1, "不可重试异常不得二次调用上游"


@pytest.mark.asyncio
async def test_retry_loop_retries_retryable(monkeypatch):
    """可重试异常仍按原策略重试 1 次（共 2 次调用）。"""
    calls = {"n": 0}

    async def fake_stream(*a, **k):
        calls["n"] += 1
        raise LLMServiceError("AI 服务繁忙", retryable=True, status_code=429)

    from app.services.ai import record_gen_v2_service as m
    monkeypatch.setattr(m.llm_client, "chat_json_stream", fake_stream)
    monkeypatch.setattr(m.asyncio, "sleep", _no_sleep)
    with pytest.raises(LLMServiceError):
        await _call_llm_json_with_retry("p", {
            "temperature": 0.3, "max_tokens": 100, "model_name": "m"})
    assert calls["n"] == 2


async def _no_sleep(_):
    return None


@pytest.mark.asyncio
async def test_qc_fix_failure_returns_degraded(async_db, monkeypatch):
    """LLM 失败时 qc-fix 回退原建议，但必须带 degraded=True + 医生可读原因。"""
    from app.services.ai import _qc_ops as m

    async def fake_chat(*a, **k):
        raise LLMServiceError("AI 账户余额不足，请联系管理员充值后再试",
                              retryable=False, status_code=402)

    monkeypatch.setattr(m.llm_client, "chat", fake_chat)
    result = await run_qc_fix(async_db, QCFixRequest(
        field_name="主诉", issue_description="缺持续时间",
        suggestion="建议补充持续时间", current_record="【主诉】\n头痛"))
    assert result["degraded"] is True
    assert result["fix_text"] == "建议补充持续时间", "回退原建议"
    assert "余额不足" in result["error"]


@pytest.mark.asyncio
async def test_qc_fix_success_not_degraded(async_db, monkeypatch):
    from app.services.ai import _qc_ops as m

    async def fake_chat(*a, **k):
        return "头痛3天，加重1天"

    async def fake_log(*a, **k):
        return None

    monkeypatch.setattr(m.llm_client, "chat", fake_chat)
    monkeypatch.setattr(m, "log_ai_task", fake_log)
    result = await run_qc_fix(async_db, QCFixRequest(
        field_name="主诉", issue_description="缺持续时间",
        suggestion="建议补充持续时间", current_record="【主诉】\n头痛3天，加重1天"))
    assert result["degraded"] is False and result["error"] is None
    assert result["fix_text"]