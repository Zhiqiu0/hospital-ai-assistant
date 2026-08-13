"""病历回写发送单测（用 httpx.MockTransport 模拟 HIS 响应）。"""
from datetime import date

import httpx
import pytest

from app.config import settings
from app.his_adapter.writeback_sender import send_writeback
from app.models.encounter import Encounter, InquiryInput
from app.models.patient import Patient


async def _make_encounter(db) -> str:
    """造一条带 HIS 标识 + 问诊的接诊，返回 encounter_id。"""
    p = Patient(name="李四", birth_date=date(1990, 5, 1))
    db.add(p)
    await db.commit()
    enc = Encounter(
        patient_id=p.id, doctor_id="doc-1", visit_type="outpatient",
        visit_no="V1", status="in_progress",
        his_external_ref={"hospital_code": "H1", "his_patient_no": "P1",
                          "his_visit_no": "V1", "his_doctor_no": "D001"},
    )
    db.add(enc)
    await db.commit()
    db.add(InquiryInput(encounter_id=enc.id, version=1, chief_complaint="咳嗽3天"))
    await db.commit()
    return enc.id


@pytest.mark.asyncio
async def test_writeback_skipped_when_url_unset(async_db, monkeypatch):
    """回写地址未配置 → skipped，不报错。"""
    monkeypatch.setattr(settings, "his_writeback_url", "")
    enc_id = await _make_encounter(async_db)
    result = await send_writeback(async_db, enc_id)
    assert result.ok is False and result.status == "skipped"


@pytest.mark.asyncio
async def test_writeback_success(async_db, monkeypatch):
    """写入 + 刷新都返回 code 0 → success，带回 his_doc_id。"""
    monkeypatch.setattr(settings, "his_writeback_url", "http://his/write")
    monkeypatch.setattr(settings, "his_writeback_refresh_url", "http://his/refresh")
    monkeypatch.setattr(settings, "his_writeback_app_id", "appMe")
    monkeypatch.setattr(settings, "his_writeback_app_secret", "sec")

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "refresh" in str(request.url):
            return httpx.Response(200, json={"code": 0, "message": "ok", "data": {}})
        return httpx.Response(200, json={"code": 0, "message": "ok", "data": {"record_id": "R9"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    enc_id = await _make_encounter(async_db)
    result = await send_writeback(async_db, enc_id, client=client)
    await client.aclose()

    assert result.ok is True and result.status == "success"
    assert result.his_doc_id == "R9"
    assert any("write" in c for c in calls) and any("refresh" in c for c in calls)


@pytest.mark.asyncio
async def test_writeback_his_returns_error_code(async_db, monkeypatch):
    """HIS 写入返回 code!=0 → write_failed，不再调刷新。"""
    monkeypatch.setattr(settings, "his_writeback_url", "http://his/write")
    monkeypatch.setattr(settings, "his_writeback_refresh_url", "http://his/refresh")
    monkeypatch.setattr(settings, "his_writeback_app_id", "appMe")
    monkeypatch.setattr(settings, "his_writeback_app_secret", "sec")

    refresh_called = {"v": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if "refresh" in str(request.url):
            refresh_called["v"] = True
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(200, json={"code": 40004, "message": "参数错误"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    enc_id = await _make_encounter(async_db)
    result = await send_writeback(async_db, enc_id, client=client)
    await client.aclose()

    assert result.ok is False and result.status == "write_failed"
    assert "40004" in result.message
    assert refresh_called["v"] is False  # 写入失败不应触发刷新


@pytest.mark.asyncio
async def test_writeback_retries_on_5xx(async_db, monkeypatch):
    """写入先 500 后 200 → 重试后成功。"""
    monkeypatch.setattr(settings, "his_writeback_url", "http://his/write")
    monkeypatch.setattr(settings, "his_writeback_refresh_url", "")  # 不配刷新，专测写入重试
    monkeypatch.setattr(settings, "his_writeback_app_id", "appMe")
    monkeypatch.setattr(settings, "his_writeback_app_secret", "sec")
    monkeypatch.setattr(settings, "his_writeback_max_retries", 2)

    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503, json={"code": -1})
        return httpx.Response(200, json={"code": 0, "data": {"record_id": "R1"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    enc_id = await _make_encounter(async_db)
    result = await send_writeback(async_db, enc_id, client=client)
    await client.aclose()

    assert result.ok is True and result.status == "success"
    assert attempts["n"] == 2  # 第一次 503，重试第二次 200


@pytest.mark.asyncio
async def test_writeback_status_persisted_to_his_ref(async_db, monkeypatch):
    """回写结果落库：his_external_ref.writeback 记录 status/ok/his_doc_id。"""
    monkeypatch.setattr(settings, "his_writeback_url", "http://his/write")
    monkeypatch.setattr(settings, "his_writeback_refresh_url", "")
    monkeypatch.setattr(settings, "his_writeback_app_id", "appMe")
    monkeypatch.setattr(settings, "his_writeback_app_secret", "sec")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"record_id": "R7"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    enc_id = await _make_encounter(async_db)
    result = await send_writeback(async_db, enc_id, client=client)
    await client.aclose()

    assert result.ok is True
    enc = await async_db.get(Encounter, enc_id)
    wb = enc.his_external_ref["writeback"]
    assert wb["status"] == "success" and wb["ok"] is True
    assert wb["his_doc_id"] == "R7" and wb["at"]


@pytest.mark.asyncio
async def test_writeback_skipped_also_persisted(async_db, monkeypatch):
    """skipped（未配置地址且 WS 离线）也落库，队列能提示医生未回写。"""
    monkeypatch.setattr(settings, "his_writeback_url", "")
    enc_id = await _make_encounter(async_db)
    await send_writeback(async_db, enc_id)
    enc = await async_db.get(Encounter, enc_id)
    assert enc.his_external_ref["writeback"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_failed_writeback_preserves_reconcile_counters(async_db, monkeypatch):
    """失败回写落库必须保留对账计数（2026-08-13 复检修复的回归锁）。

    修复前 _persist_writeback_status 整体替换 writeback 字典，把
    reconcile_attempts / reconcile_exhausted 抹掉——而对账是「先重投（抹零）
    再累加（+1）」，计数恒为 1，5 次上限与耗尽告警永不触发，失败回写被无限静默重投。
    """
    monkeypatch.setattr(settings, "his_writeback_url", "")  # → skipped（可重试状态）
    enc_id = await _make_encounter(async_db)
    # 模拟对账已累计 4 次失败
    enc = await async_db.get(Encounter, enc_id)
    enc.his_external_ref = {**enc.his_external_ref,
                            "writeback": {"status": "write_failed",
                                          "reconcile_attempts": 4}}
    await async_db.commit()

    await send_writeback(async_db, enc_id)

    await async_db.refresh(enc)
    wb = enc.his_external_ref["writeback"]
    assert wb["status"] == "skipped"          # 新结果已落库
    assert wb["reconcile_attempts"] == 4      # 计数未被抹掉（关键）


@pytest.mark.asyncio
async def test_successful_writeback_clears_reconcile_counters(async_db, monkeypatch):
    """回写成功即对账结束：清零计数，历史失败不影响将来的重投判定。"""
    monkeypatch.setattr(settings, "his_writeback_url", "http://his/write")
    monkeypatch.setattr(settings, "his_writeback_refresh_url", "")
    monkeypatch.setattr(settings, "his_writeback_app_id", "appMe")
    monkeypatch.setattr(settings, "his_writeback_app_secret", "sec")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"record_id": "R9"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    enc_id = await _make_encounter(async_db)
    enc = await async_db.get(Encounter, enc_id)
    enc.his_external_ref = {**enc.his_external_ref,
                            "writeback": {"status": "write_failed",
                                          "reconcile_attempts": 3}}
    await async_db.commit()

    result = await send_writeback(async_db, enc_id, client=client)
    await client.aclose()

    assert result.ok is True
    await async_db.refresh(enc)
    wb = enc.his_external_ref["writeback"]
    assert wb["status"] == "success"
    assert "reconcile_attempts" not in wb and "reconcile_exhausted" not in wb
