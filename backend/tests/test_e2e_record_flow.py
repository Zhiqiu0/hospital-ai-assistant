"""病历全链路集成测试（2026-08-11 病历可信）：接诊→签发→电子签名→回写状态落库。

串起真实 service 代码（admit_service / quick_save / send_writeback），只 mock 外部
HIS 传输（WS/HTTP），验证第一版 HIS 最关键的"病历生成到回写"闭环不断链。
"""
import pytest

from app.his_adapter.admit_service import process_admit
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.user import User
from app.services._record_signature import verify_version
from app.services.medical_record_service import MedicalRecordService
from sqlalchemy import select


async def _mk_doctor(db, code="E1"):
    doc = User(username=code, password_hash="x", real_name="集成医生",
               role="doctor", employee_no=code, is_active=True)
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


def _admit(**kw):
    base = {"visit_id": "E2E-V1", "hospital_code": "H1", "patient_name": "集成患者",
            "doctor_code": "E1", "gender": "male"}
    base.update(kw)
    return AdmitPushRequest(**base)


@pytest.mark.asyncio
async def test_admit_to_sign_to_writeback_chain(async_db, monkeypatch):
    """完整链路：HIS 接诊推送 → 建档派医生 → 签发（带电子签名）→ 回写状态落库。"""
    await _mk_doctor(async_db)

    # 1. 接诊推送 → 建档 + 建接诊
    result = await process_admit(async_db, _admit())
    enc_id = result.encounter_id
    doctor_id = result.doctor_id

    # 2. 签发病历
    svc = MedicalRecordService(async_db)
    record = await svc.quick_save(enc_id, "outpatient",
                                  "主诉：集成测试。\n现病史：全链路验证。", doctor_id)
    assert record.status == "submitted"

    # 3. 电子签名哈希已生成且校验通过
    ver = (await async_db.execute(
        select(RecordVersion).where(RecordVersion.medical_record_id == record.id,
                                    RecordVersion.version_no == record.current_version)
    )).scalar_one()
    assert ver.sign_hash and await verify_version(async_db, ver) is True

    # 4. 接诊已关闭（门诊签发即结束）
    enc = await async_db.get(Encounter, enc_id)
    assert enc.status == "completed"

    # 5. 回写：mock 外部传输，验证状态落库进 his_external_ref.writeback
    from app.config import settings
    from app.his_adapter import writeback_sender as ws
    monkeypatch.setattr(settings, "his_writeback_url", "http://his/write")
    monkeypatch.setattr(settings, "his_writeback_app_id", "app")
    monkeypatch.setattr(settings, "his_writeback_app_secret", "sec")
    monkeypatch.setattr(settings, "his_writeback_refresh_url", "")

    import httpx

    def handler(request):
        return httpx.Response(200, json={"code": 0, "data": {"record_id": "HIS-DOC-1"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    wb = await ws.send_writeback(async_db, enc_id, client=client)
    await client.aclose()
    assert wb.ok and wb.status == "success"

    # 状态已落库，队列/对账据此判断
    enc2 = await async_db.get(Encounter, enc_id)
    assert enc2.his_external_ref["writeback"]["status"] == "success"


@pytest.mark.asyncio
async def test_cancelled_encounter_blocks_whole_chain(async_db):
    """取消的接诊无法签发（状态守卫），链路正确中断。"""
    await _mk_doctor(async_db)
    result = await process_admit(async_db, _admit(visit_id="E2E-V2"))
    enc = await async_db.get(Encounter, result.encounter_id)
    enc.status = "cancelled"
    await async_db.commit()

    svc = MedicalRecordService(async_db)
    with pytest.raises(ValueError, match="已取消"):
        await svc.quick_save(result.encounter_id, "outpatient", "x", result.doctor_id)

    # 未产生已签发病历
    recs = (await async_db.execute(
        select(MedicalRecord).where(MedicalRecord.encounter_id == result.encounter_id)
    )).scalars().all()
    assert all(r.status != "submitted" for r in recs)
