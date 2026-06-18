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
