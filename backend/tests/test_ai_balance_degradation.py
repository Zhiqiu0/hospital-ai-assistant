# -*- coding: utf-8 -*-
"""AI 余额耗尽的降级演练（2026-09-10 开业首日容量与降级专项）。

按当前余额（约 2.7 元 ≈ 36 次接诊），**开业当天余额耗尽几乎必然发生**——那一刻
全院所有医生的 AI 调用同时开始返回 402。这里把那一天在测试里提前过一遍：把
LLM 客户端替换成"只会抛 402"的替身，验证医生侧看到的是可继续工作的降级，
而不是白屏、静默或裸 traceback。

三条底线（对应真实工作流）：
  ① 质控是"规则引擎 + LLM 建议"双路——LLM 402 时规则评分（分数/等级/扣分项）
     必须照常产出，done 事件的 summary 要说清"余额不足 + 仅返回规则引擎结果"，
     医生知道发生了什么、且质控没有停摆；
  ② 规则评分照常**落库 qc_reports**——评分看板与月度通报不因 LLM 挂而断档
     （历史上 LLM 一挂整次质控零痕迹，2026-08-21 阶段0 修过，这里防回归）；
  ③ 纯 LLM 的生成路径（quick-generate）402 时产出 type=error 的 SSE 事件，
     message 是医生可读的"余额不足请联系管理员充值"，而不是异常类型名。

不真烧余额：替身在 llm_client 层注入，网络零请求。
"""
from datetime import datetime

import pytest

from app.models.encounter import Encounter
from app.models.patient import Patient
from app.services.ai.llm_client import LLMServiceError

BALANCE_402 = LLMServiceError(
    "AI 账户余额不足，请联系管理员充值后再试", retryable=False, status_code=402,
)

# 内容凑齐必填章节，让规则引擎能给出正经分数（这不是在测规则本身，
# 但分数得是真算出来的，才能证明"规则路完全不依赖 LLM"）
RECORD = """【主诉】
咳嗽3天
【现病史】
患者3天前受凉后出现咳嗽，咳白痰，无发热。
【既往史】
既往体质可。
【过敏史】
否认食物药物过敏史。
【体格检查】
T:36.5℃ P:78次/分 R:18次/分 BP:120/78mmHg
双肺呼吸音清。
【诊断】
西医诊断：急性支气管炎
【治疗意见及措施】
处理意见：头孢呋辛酯片0.25g bid po
"""


async def _mk_encounter(db) -> str:
    p = Patient(name="降级演练", gender="male")
    db.add(p)
    await db.flush()
    e = Encounter(patient_id=p.id, doctor_id="doc-1", visit_type="outpatient",
                  visited_at=datetime.now())
    db.add(e)
    await db.commit()
    return e.id


@pytest.mark.asyncio
async def test_余额耗尽时质控降级为规则引擎但不停摆(async_db, monkeypatch):
    from app.schemas.ai_request import QuickQCRequest
    from app.services.ai import qc_stream_service

    async def _broke(*a, **k):
        raise BALANCE_402

    monkeypatch.setattr(qc_stream_service.llm_client, "chat_json_stream", _broke)

    enc_id = await _mk_encounter(async_db)
    req = QuickQCRequest(content=RECORD, record_type="outpatient",
                         encounter_id=enc_id)
    events = [e async for e in qc_stream_service.run_quick_qc_stream(async_db, req)]
    by_type = {e["type"]: e for e in events}

    # ① 规则评分照常产出且是真分数
    assert "rule_issues" in by_type, f"规则事件缺失，收到：{[e['type'] for e in events]}"
    assert isinstance(by_type["rule_issues"]["grade_score"], (int, float))

    # ② done 事件把"为什么没有 AI 建议"说给医生听
    done = by_type.get("done")
    assert done, "缺 done 事件——前端会一直转圈"
    assert "余额不足" in done["summary"], f"降级原因没进 summary：{done['summary']}"
    assert "规则引擎" in done["summary"]
    # 分数在降级事件里也要在（前端状态条直接用它）
    assert done["grade_score"] == by_type["rule_issues"]["grade_score"]


@pytest.mark.asyncio
async def test_余额耗尽时评分仍落库(async_db, monkeypatch):
    """看板与月度通报的根。历史上 LLM 一挂整次质控零痕迹（qc_reports 依赖
    LLM 成功），2026-08-21 阶段0 修为"规则评分一出即落库"——这里防回归。

    save_qc_report 是 fire-and-forget，走全局 AsyncSessionLocal 另开会话；
    把它 patch 到本用例的测试 engine 上，落库才真的可断言。"""
    from sqlalchemy import text

    from app.schemas.ai_request import QuickQCRequest
    from app.services.ai import qc_stream_service, task_logger

    async def _broke(*a, **k):
        raise BALANCE_402

    monkeypatch.setattr(qc_stream_service.llm_client, "chat_json_stream", _broke)

    # SQLite :memory: 每个新连接是独立空库——另起 sessionmaker 会连到没有表的
    # 新库（第一版就是这么写错的）。让 fire-and-forget 会话复用本用例的
    # session：包一层不 close 的 async 上下文（真 close 会毁掉 fixture）。
    class _SameSession:
        async def __aenter__(self):
            return async_db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(task_logger, "AsyncSessionLocal", lambda: _SameSession())

    enc_id = await _mk_encounter(async_db)
    req = QuickQCRequest(content=RECORD, record_type="outpatient",
                         encounter_id=enc_id)
    async for _ in qc_stream_service.run_quick_qc_stream(async_db, req):
        pass
    n = (await async_db.execute(text(
        "SELECT count(*) FROM qc_reports WHERE encounter_id = :e"
    ), {"e": enc_id})).scalar()
    assert n and n >= 1, "LLM 402 时评分没落库——看板将在余额耗尽期间断档"


@pytest.mark.asyncio
async def test_余额耗尽时生成给出医生可读的错误(async_db, monkeypatch):
    """quick-generate 是纯 LLM 路径，没有规则兜底——402 时必须是明确的 error
    事件 + 可读文案，医生转头手写病历（那条链路不碰 LLM，照常可用）。"""
    import json

    from app.schemas.ai_request import QuickGenerateRequest
    from app.services.ai import record_gen_v2_service as gen

    async def _broke(*a, **k):
        raise BALANCE_402

    monkeypatch.setattr(gen.llm_client, "chat_json_stream", _broke)

    enc_id = await _mk_encounter(async_db)
    req = QuickGenerateRequest(encounter_id=enc_id, record_type="outpatient",
                               chief_complaint="咳嗽3天")
    chunks = []
    async for sse in gen.stream_record_v2("outpatient", req, async_db):
        # sse_event 产出 "data: {...}\n\n" 字符串
        raw = sse[5:].strip() if isinstance(sse, str) and sse.startswith("data:") else sse
        try:
            chunks.append(json.loads(raw))
        except (TypeError, ValueError):
            pass
    errors = [c for c in chunks if c.get("type") == "error"]
    assert errors, f"402 没有产出 error 事件，收到类型：{[c.get('type') for c in chunks]}"
    assert "余额不足" in errors[0]["message"], errors[0]
    assert "充值" in errors[0]["message"]
