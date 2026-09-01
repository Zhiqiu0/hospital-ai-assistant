# -*- coding: utf-8 -*-
"""整改后再次退回不能被防重吞掉（2026-09-02 质控闭环实测发现）。

场景：质控员退回 → 管理员按意见修订 → 医生还是没改到点上 → 质控员再次退回
同样的意见。原防重判据拿 medical_records.submitted_at 当基线，而它是**首次**
签发时间、只写一次（sign_hash 的哈希输入依赖它，覆写会让所有历史版本被永久判
为已篡改，见 _medical_record_sign 的说明），于是
`latest.created_at >= submitted_at` 恒成立，第二次退回被判"重复提交"吞掉。

后果不是少一行数据：
  · 质控员看到成功提示，以为退回已送达；
  · 医生端的退回提醒**消失**——my-returned 认最新那条 review，它早于修订时刻，
    被判"已整改"出清单，医生以为整改被接受了；
  · 月度通报少记一次退回。
双方都以为事情在推进，实际停摆在那份没改好的版本上。

生产实测复现：第二次退回返回 {"duplicate": true}，医生端 my-returned 为空。

本文件走真实端点（不复刻判据）——复刻判据的用例正是 2026-09-01 那次
"7 条全绿而真实请求缺字段"栽过的坑。
"""
from datetime import date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.medical_record import RecordVersion
from app.models.patient import Patient
from app.models.user import User
from app.services.medical_record_service import MedicalRecordService

OPINION = "现病史过于简略，请补全既往史与体格检查"


def _user(uid: str, role: str):
    return User(id=uid, username=f"u_{uid}", password_hash="x", real_name=f"用户{uid}",
                role=role, is_active=True)


def _client_as(async_db, user) -> AsyncClient:
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest_asyncio.fixture
async def signed_record(async_db):
    async_db.add(Patient(id="p-rr", name="再退回", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(id="enc-rr", patient_id="p-rr", doctor_id="doc-1",
                           visit_type="outpatient", status="in_progress",
                           visited_at=datetime.now()))
    await async_db.flush()
    rec = await MedicalRecordService(async_db).quick_save(
        encounter_id="enc-rr", record_type="outpatient",
        content="第一版：过于简略", doctor_id="doc-1")
    return rec.id


@pytest.mark.asyncio
async def test_整改后再次退回不算重复(async_db, signed_record):
    officer = _user("qc-1", "qc_officer")
    async with _client_as(async_db, officer) as ac:
        r1 = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": signed_record, "conclusion": "returned",
            "comment": OPINION})
        assert r1.status_code == 200, r1.text
        first_id = r1.json()["review_id"]

        # 管理员按意见修订（门急诊的整改通道），产出 admin_revise 版本
        async_db.add(RecordVersion(
            medical_record_id=signed_record, version_no=2,
            content={"text": "第二版：还是没改好"}, source="admin_revise",
            created_at=datetime.now()))
        await async_db.commit()

        r2 = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": signed_record, "conclusion": "returned",
            "comment": OPINION})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body.get("duplicate") is not True, "整改后的再次退回被判成了重复提交"
        assert body["review_id"] != first_id, "第二次退回没有真正落库"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_真双击仍然幂等(async_db, signed_record):
    """两次提交之间没有新的签发/修订版本——这正是防重要挡的场景，不能放过。"""
    officer = _user("qc-1", "qc_officer")
    async with _client_as(async_db, officer) as ac:
        r1 = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": signed_record, "conclusion": "returned",
            "comment": OPINION})
        r2 = await ac.post("/api/v1/qc/reviews", json={
            "medical_record_id": signed_record, "conclusion": "returned",
            "comment": OPINION})
        assert r2.json().get("duplicate") is True, "双击提交被重复计入复核数"
        assert r2.json()["review_id"] == r1.json()["review_id"]
    app.dependency_overrides.clear()
