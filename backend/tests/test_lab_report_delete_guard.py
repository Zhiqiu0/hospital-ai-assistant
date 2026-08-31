# -*- coding: utf-8 -*-
"""检验报告删除的合规守卫（2026-08-31 法规逐条对照审计）。

检验报告是**客观病历资料**：《医疗纠纷预防和处理条例》明令不得隐匿、销毁，
《电子病历应用管理规范》第二十四条要求门诊病历至少保存 15 年。而删除端点此前
是硬删除（磁盘原图连同数据库行一起没），并且是全仓唯一一类**既不可逆、又完全
不留审计痕迹**的操作——同类的 PACS 报告删除早就有"已发布报告 409 拒删"的保护。

出事场景：病历正文写着"血常规示 WBC 12.3×10⁹/L 支持感染诊断"，对应化验单原图
被误删。三年后纠纷，法院要求提交客观检验资料——文件和行都不在，审计日志里也
查不到是谁删的。医院既拿不出证据，也说不清是谁销毁的。
"""
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.lab_report import LabReport
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.models.user import User


@pytest_asyncio.fixture
async def api(async_db, monkeypatch):
    """注意 log_action 是 fire-and-forget、用**独立**数据库会话写入，测试库里
    查不到它写的行；这里改为捕获调用参数，测的是"端点确实报了审计"这层契约。"""
    calls: list[dict] = []

    async def _spy(**kw):
        calls.append(kw)

    monkeypatch.setattr("app.api.v1.lab_reports.log_action", _spy)
    transport = ASGITransport(app=app)
    doctor = User(username="lab_doc", password_hash="x", real_name="李医生",
                  role="doctor", is_active=True)
    async_db.add(doctor)
    await async_db.commit()
    await async_db.refresh(doctor)

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: doctor
    yield async_db, doctor, AsyncClient(transport=transport, base_url="http://test"), calls
    app.dependency_overrides.clear()


async def _mk_encounter(db, doctor, *, signed: bool) -> str:
    """建一个接诊 + 一份检验报告；signed=True 时该接诊已有签发病历。"""
    patient = Patient(name="王五", gender="male")
    db.add(patient)
    await db.flush()
    enc = Encounter(patient_id=patient.id, doctor_id=doctor.id,
                    visit_type="outpatient", visited_at=datetime.now())
    db.add(enc)
    await db.flush()
    db.add(LabReport(id=f"lr-{enc.id}", doctor_id=doctor.id, encounter_id=enc.id,
                     status="done", file_path=f"lab_reports/{enc.id}/x.pdf",
                     original_filename="血常规.pdf"))
    if signed:
        db.add(MedicalRecord(encounter_id=enc.id, record_type="outpatient",
                             status="submitted", current_version=1, record_no=1))
    await db.commit()
    return enc.id


@pytest.mark.asyncio
async def test_病历已签发后检验报告不得删除(api):
    db, doctor, client, calls = api
    enc_id = await _mk_encounter(db, doctor, signed=True)
    async with client as ac:
        res = await ac.delete(f"/api/v1/lab-reports/lr-{enc_id}")
    assert res.status_code == 409, "已签发病历的客观资料被允许删除了"

    # 行仍在：不是"报了错但已经删了"
    still = (await db.execute(
        select(LabReport).where(LabReport.id == f"lr-{enc_id}"))).scalar_one_or_none()
    assert still is not None


@pytest.mark.asyncio
async def test_被拒的删除同样留审计痕迹(api):
    """未遂的销毁企图也要能查到——这正是纠纷时要还原的东西。"""
    db, doctor, client, calls = api
    enc_id = await _mk_encounter(db, doctor, signed=True)
    async with client as ac:
        await ac.delete(f"/api/v1/lab-reports/lr-{enc_id}")

    assert calls, "删除被拒没有写审计日志"
    assert calls[0]["action"] == "delete_lab_report"
    assert calls[0]["status"] == "denied"


@pytest.mark.asyncio
async def test_未签发时可删但必须留审计(api):
    """医生传错病人的化验单仍然要能删掉——但删了必须查得到是谁删的。"""
    db, doctor, client, calls = api
    enc_id = await _mk_encounter(db, doctor, signed=False)
    async with client as ac:
        res = await ac.delete(f"/api/v1/lab-reports/lr-{enc_id}")
    assert res.status_code == 200

    gone = (await db.execute(
        select(LabReport).where(LabReport.id == f"lr-{enc_id}"))).scalar_one_or_none()
    assert gone is None

    assert calls, "删除成功却没有审计日志——这是全仓唯一不可逆的操作"
    assert calls[0]["action"] == "delete_lab_report"
    assert "血常规.pdf" in (calls[0]["detail"] or ""), "审计详情应能指认删掉的是哪份报告"
