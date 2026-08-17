"""
AI 建议反馈服务单元测试（app/services/ai_feedback_service.py）

覆盖范围：
  - submit_feedback 入参校验：verdict / suggestion_category 白名单 → 400
  - 反馈写入主路径：记录落库 + doctor_id / verdict / comment 正确
  - 生成链路标签（2026-08-18 起提示词/模型参数归代码维护，标签常量推导）：
      inquiry / exam 类别 → prompt_scene 对应、prompt_version 'hardcoded'
      diagnosis 类别（无对应 prompt scene）→ scene / version 都为 None
      model_name 恒为全局默认 settings.deepseek_model

说明：data 入参只被服务按属性读取，用 SimpleNamespace 模拟 FeedbackIn
请求体（避免为单元测试引入整条 API 路由依赖链）。
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models.ai_feedback import AISuggestionFeedback
from app.services.ai_feedback_service import AIFeedbackService


def _doctor():
    """模拟当前登录医生（服务只读 id / username）。"""
    return SimpleNamespace(id="doc-fb-1", username="doctor_fb")


def _payload(**overrides):
    """构造一条合法反馈请求体，允许按需覆盖字段。"""
    base = dict(
        encounter_id="enc-fb-1",
        suggestion_category="inquiry",
        suggestion_id="sug-001",
        suggestion_text="是否有夜间盗汗？",
        verdict="useful",
        comment=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── 入参校验 ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_verdict_rejected(async_db):
    """verdict 不在 useful/useless 白名单 → 400，不落库。"""
    svc = AIFeedbackService(async_db)
    with pytest.raises(HTTPException) as exc:
        await svc.submit_feedback(_payload(verdict="great"), _doctor())
    assert exc.value.status_code == 400
    rows = (await async_db.execute(select(AISuggestionFeedback))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_invalid_category_rejected(async_db):
    """suggestion_category 不在 inquiry/exam/diagnosis 白名单 → 400。"""
    svc = AIFeedbackService(async_db)
    with pytest.raises(HTTPException) as exc:
        await svc.submit_feedback(_payload(suggestion_category="surgery"), _doctor())
    assert exc.value.status_code == 400


# ── 写入主路径与版本标签解析 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feedback_written_with_code_prompt_labels(async_db):
    """写入成功，并打上代码内置提示词的标签：prompt_version 'hardcoded'、默认模型。

    'hardcoded' 沿用历史数据的口径，未来做 prompt 优化时据此按版本分层，
    避免数据污染。
    """
    svc = AIFeedbackService(async_db)
    result = await svc.submit_feedback(
        _payload(verdict="useless", comment="追问太宽泛"), _doctor())
    assert result["ok"] is True

    fb = await async_db.get(AISuggestionFeedback, result["id"])
    assert fb.doctor_id == "doc-fb-1"
    assert fb.verdict == "useless"
    assert fb.comment == "追问太宽泛"
    assert fb.prompt_scene == "inquiry"
    assert fb.prompt_version == "hardcoded"  # 提示词全部代码内置
    assert fb.model_name == settings.deepseek_model  # 全局默认模型


@pytest.mark.asyncio
async def test_exam_category_labels(async_db):
    """exam 类别：prompt_scene 'exam'、version 'hardcoded'。"""
    result = await AIFeedbackService(async_db).submit_feedback(
        _payload(suggestion_category="exam"), _doctor())
    fb = await async_db.get(AISuggestionFeedback, result["id"])
    assert fb.prompt_scene == "exam"
    assert fb.prompt_version == "hardcoded"


@pytest.mark.asyncio
async def test_diagnosis_category_has_no_prompt_scene(async_db):
    """diagnosis 类别暂无对应 prompt 模板：scene/version 都为 None（非 'hardcoded'）。"""
    result = await AIFeedbackService(async_db).submit_feedback(
        _payload(suggestion_category="diagnosis"), _doctor())
    fb = await async_db.get(AISuggestionFeedback, result["id"])
    assert fb.prompt_scene is None
    assert fb.prompt_version is None
    # 模型名仍要打标（全局默认模型），保证标签永不为空
    assert fb.model_name == settings.deepseek_model
