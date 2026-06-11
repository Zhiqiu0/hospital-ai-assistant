"""
AI 建议反馈服务单元测试（app/services/ai_feedback_service.py）

覆盖范围：
  - submit_feedback 入参校验：verdict / suggestion_category 白名单 → 400
  - 反馈写入主路径：记录落库 + doctor_id / verdict / comment 正确
  - prompt_version 解析三态：
      有激活模板 → 取模板 version
      无激活模板（或模板被停用）→ fallback 'hardcoded'
      diagnosis 类别（无对应 prompt scene）→ None
  - model_name 解析：有激活 ModelConfig(scene=suggestions) → 取其 model_name；
    没有 → fallback settings.deepseek_model

说明：data 入参只被服务按属性读取，用 SimpleNamespace 模拟 FeedbackIn
请求体（避免为单元测试引入整条 API 路由依赖链）。
"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models.ai_feedback import AISuggestionFeedback
from app.models.config import ModelConfig, PromptTemplate
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
async def test_feedback_written_with_hardcoded_fallback(async_db):
    """无激活 prompt 模板时：写入成功，prompt_version 回退 'hardcoded'。

    这是"代码硬编码 prompt 时期"的标签，未来做 prompt 优化时
    据此把旧反馈和可配置模板时期的反馈分层，避免数据污染。
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
    assert fb.prompt_version == "hardcoded"  # DB 无 active 模板 → fallback
    # DB 无 ModelConfig(scene=suggestions) → 回退全局默认模型
    assert fb.model_name == settings.deepseek_model


@pytest.mark.asyncio
async def test_feedback_uses_active_prompt_version(async_db):
    """有激活模板时取其 version；多版本取 created_at 最新的。"""
    async_db.add_all([
        PromptTemplate(name="问诊v3", scene="inquiry", content="...", version="v3",
                       is_active=True, created_at=datetime(2026, 6, 1, 8, 0)),
        PromptTemplate(name="问诊v7", scene="inquiry", content="...", version="v7",
                       is_active=True, created_at=datetime(2026, 6, 5, 8, 0)),
    ])
    await async_db.commit()

    result = await AIFeedbackService(async_db).submit_feedback(_payload(), _doctor())
    fb = await async_db.get(AISuggestionFeedback, result["id"])
    assert fb.prompt_version == "v7"


@pytest.mark.asyncio
async def test_inactive_prompt_falls_back_to_hardcoded(async_db):
    """模板存在但被停用（is_active=False）→ 视为无模板，仍回退 'hardcoded'。"""
    async_db.add(PromptTemplate(name="停用模板", scene="exam", content="...",
                                version="v9", is_active=False))
    await async_db.commit()

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
    # 模型名仍要解析（diagnosis 也映射到 suggestions 模型场景，无配置则回退默认）
    assert fb.model_name == settings.deepseek_model


@pytest.mark.asyncio
async def test_model_name_from_active_model_config(async_db):
    """存在激活的 ModelConfig(scene=suggestions) 时优先取其 model_name。"""
    async_db.add(ModelConfig(scene="suggestions", model_name="qwen-max",
                             is_active=True))
    await async_db.commit()

    result = await AIFeedbackService(async_db).submit_feedback(_payload(), _doctor())
    fb = await async_db.get(AISuggestionFeedback, result["id"])
    assert fb.model_name == "qwen-max"


@pytest.mark.asyncio
async def test_inactive_model_config_falls_back_to_default(async_db):
    """ModelConfig 被停用 → 回退 settings.deepseek_model（保证标签永不为空）。"""
    async_db.add(ModelConfig(scene="suggestions", model_name="qwen-max",
                             is_active=False))
    await async_db.commit()

    result = await AIFeedbackService(async_db).submit_feedback(_payload(), _doctor())
    fb = await async_db.get(AISuggestionFeedback, result["id"])
    assert fb.model_name == settings.deepseek_model
