"""批量补全 service 测试（test_supplement_batch.py）

替换 test_record_supplement_polish.py —— 旧 supplement"整段重画"路径已下线。

新 service 行为契约（services/ai/supplement_batch_service.py）：
  1. 空 qc_issues / 全 __xxx__ 标记字段 → 返回 {items: []}（不调 LLM）
  2. LLM 返回非合法 items（非 list、漏 field_name、字段名不在清单等）→ 丢弃
  3. LLM 编造的字段名（不在请求清单内）→ 丢弃（防写入错位）
  4. 同名字段去重保留首个
  5. LLM 调用异常 → 返回 {items: [], error: ...} 不抛
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ai import supplement_batch_service as svc


def _mock_req(**overrides):
    """构造与 SupplementRequest 兼容的 mock 对象。"""
    base = dict(
        record_type="outpatient",
        chief_complaint="头痛 3 天",
        history_present_illness="搏动性头痛",
        current_content="【主诉】头痛 3 天\n【现病史】搏动性头痛...\n【体格检查】\n切诊·舌象：[未填写，需补充]\n",
        qc_issues=[
            {"field_name": "舌象", "issue_description": "缺切诊·舌象", "suggestion": "请补充"},
            {"field_name": "脉象", "issue_description": "缺切诊·脉象", "suggestion": "请补充"},
        ],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_empty_qc_issues_short_circuits():
    """qc_issues 为空 → 不调 LLM，直接返 {items: []}。"""
    req = _mock_req(qc_issues=[])
    result = await svc.run_quick_supplement_batch(db=None, req=req)
    assert result == {"items": []}


@pytest.mark.asyncio
async def test_only_non_writable_fields_short_circuits():
    """所有 issue 都是 __xxx__ 不可写字段 → 不调 LLM，直接返空。"""
    req = _mock_req(qc_issues=[
        {"field_name": "__patient_basic_info__", "issue_description": "缺", "suggestion": ""},
        {"field_name": "__visit_time__", "issue_description": "缺", "suggestion": ""},
    ])
    result = await svc.run_quick_supplement_batch(db=None, req=req)
    assert result == {"items": []}


@pytest.mark.asyncio
async def test_happy_path_returns_filtered_items(monkeypatch):
    """LLM 正常返回 → 字段名在清单内 → 通过；字段名编造 → 丢弃。"""
    async def fake_chat(*_a, **_kw):
        return {"items": [
            {"field_name": "舌象", "value": "舌淡红苔薄白"},
            {"field_name": "脉象", "value": "脉浮紧"},
            {"field_name": "编造字段", "value": "应被丢弃"},  # 不在请求清单
            {"field_name": "舌象", "value": "重复应跳过"},      # 同名去重
        ]}
    monkeypatch.setattr(svc.llm_client, "chat_json_stream", fake_chat)
    monkeypatch.setattr(svc, "get_model_options", AsyncMock(return_value={
        "temperature": 0.7, "max_tokens": 1000, "model_name": "test"
    }))
    monkeypatch.setattr(svc, "log_ai_task", AsyncMock())
    # 模拟 _last_usage
    svc.llm_client._last_usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20)

    # db 传 AsyncMock：service 在调 LLM 前会 await db.commit() 释放连接池连接，
    # 需要一个可 await 的 commit（旧测试传 None 是因当时 db 仅被已 mock 的
    # get_model_options 使用）。
    result = await svc.run_quick_supplement_batch(db=AsyncMock(), req=_mock_req())
    assert "items" in result
    items = result["items"]
    assert len(items) == 2
    names = [it["field_name"] for it in items]
    assert "舌象" in names
    assert "脉象" in names
    assert "编造字段" not in names


@pytest.mark.asyncio
async def test_llm_exception_returns_error_not_raises(monkeypatch):
    """LLM 调用抛异常 → 返回 {items: [], error: ...} 不向上抛。"""
    async def fake_chat(*_a, **_kw):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(svc.llm_client, "chat_json_stream", fake_chat)
    monkeypatch.setattr(svc, "get_model_options", AsyncMock(return_value={
        "temperature": 0.7, "max_tokens": 1000, "model_name": "test"
    }))

    result = await svc.run_quick_supplement_batch(db=AsyncMock(), req=_mock_req())
    assert result["items"] == []
    assert "error" in result


@pytest.mark.asyncio
async def test_llm_returns_non_list_items_is_safe(monkeypatch):
    """LLM 返回 items 非 list（违规）→ 安全降级为 []。"""
    async def fake_chat(*_a, **_kw):
        return {"items": "not a list"}
    monkeypatch.setattr(svc.llm_client, "chat_json_stream", fake_chat)
    monkeypatch.setattr(svc, "get_model_options", AsyncMock(return_value={
        "temperature": 0.7, "max_tokens": 1000, "model_name": "test"
    }))
    monkeypatch.setattr(svc, "log_ai_task", AsyncMock())
    svc.llm_client._last_usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0)

    result = await svc.run_quick_supplement_batch(db=AsyncMock(), req=_mock_req())
    assert result == {"items": []}


@pytest.mark.asyncio
async def test_value_empty_or_non_string_dropped(monkeypatch):
    """value 为空字符串 / 非字符串 → 丢弃该 item。"""
    async def fake_chat(*_a, **_kw):
        return {"items": [
            {"field_name": "舌象", "value": ""},          # 空字符串 → 丢
            {"field_name": "脉象", "value": 123},          # 数字 → 丢
        ]}
    monkeypatch.setattr(svc.llm_client, "chat_json_stream", fake_chat)
    monkeypatch.setattr(svc, "get_model_options", AsyncMock(return_value={
        "temperature": 0.7, "max_tokens": 1000, "model_name": "test"
    }))
    monkeypatch.setattr(svc, "log_ai_task", AsyncMock())
    svc.llm_client._last_usage = SimpleNamespace(prompt_tokens=0, completion_tokens=0)

    result = await svc.run_quick_supplement_batch(db=AsyncMock(), req=_mock_req())
    assert result["items"] == []


def test_render_issues_block_skips_empty_and_non_writable():
    """_render_issues_block 跳过 field_name 为空 / __xxx__ 标记的 issue。"""
    issues = [
        {"field_name": "舌象", "issue_description": "缺", "suggestion": "请补"},
        {"field_name": "", "issue_description": "无字段"},                # 跳过
        {"field_name": "__patient_basic_info__", "issue_description": "缺"},  # 跳过
        {"field_name": "脉象", "issue_description": "缺"},
    ]
    block, count = svc._render_issues_block(issues)
    assert count == 2
    assert "舌象" in block
    assert "脉象" in block
    assert "__patient_basic_info__" not in block
