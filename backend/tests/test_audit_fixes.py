"""审计修复的行为测试（2026-08-11）：quick_save 状态守卫 + HIS 查重收紧。"""
import pytest

from app.his_adapter.admit_service import process_admit
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User
from app.services.medical_record_service import MedicalRecordService


async def _mk_encounter(db, *, status="in_progress", visit_type="outpatient") -> str:
    p = Patient(name="测试患者")
    db.add(p)
    await db.flush()
    doc = User(username="d_sign", password_hash="x", real_name="医生", role="doctor")
    db.add(doc)
    await db.flush()
    enc = Encounter(patient_id=p.id, doctor_id=doc.id, visit_type=visit_type,
                    status=status)
    db.add(enc)
    await db.commit()
    await db.refresh(enc)
    return enc.id, doc.id


@pytest.mark.asyncio
async def test_quick_save_rejects_cancelled_encounter(async_db):
    """已取消接诊不能被签发'复活'（状态守卫）。"""
    enc_id, doc_id = await _mk_encounter(async_db, status="cancelled")
    service = MedicalRecordService(async_db)
    with pytest.raises(ValueError, match="已取消"):
        await service.quick_save(enc_id, "outpatient", "病历正文", doc_id)


@pytest.mark.asyncio
async def test_quick_save_idempotent_on_submitted(async_db):
    """已签发门诊病历**同内容**重复签发 → 幂等返回原记录，不改写。

    这是前端双击/网络重试的真实场景：同一份正文提交两次，第二次不该涨版本。
    """
    enc_id, doc_id = await _mk_encounter(async_db)
    service = MedicalRecordService(async_db)
    r1 = await service.quick_save(enc_id, "outpatient", "第一次", doc_id)
    v1 = r1.current_version
    r2 = await service.quick_save(enc_id, "outpatient", "第一次", doc_id)
    assert r2.id == r1.id
    assert r2.current_version == v1  # 版本号未涨，未重复改写


@pytest.mark.asyncio
async def test_quick_save_已签发门诊改内容必须报错而不是假装成功(async_db):
    """内容变了还回 ok，是 2026-09-02 质控复核台实测抓到的断链点。

    原实现对已签发门急诊病历无条件 return record，于是「质控退回 → 医生整改
    → 重新签发」这条闭环是这样断的：医生按整改意见改完正文，点签发，接口回
    {"ok": true}，医生以为交差了——而整改内容一个字都没落库，版本表里还是被
    退回的那一版。队列收不到（没产生新签发版本），医生端退回横幅也不消
    （判据同源）。实测中质控员随后"复核通过"的，正是那份没改过的病历。

    「不改写已签发病历」是对的，必须保持；错的是不告诉医生。
    """
    from fastapi import HTTPException

    enc_id, doc_id = await _mk_encounter(async_db)
    service = MedicalRecordService(async_db)
    r1 = await service.quick_save(enc_id, "outpatient", "被退回的劣质病历", doc_id)
    v1 = r1.current_version

    with pytest.raises(HTTPException) as exc:
        await service.quick_save(enc_id, "outpatient", "整改后的完整病历", doc_id)
    assert exc.value.status_code == 409
    assert "修订" in exc.value.detail, "报错要指出整改该走哪条通道"

    # 正文确实没被改写——法定文书不因一次被拒的写入而变样
    from sqlalchemy import select

    from app.models.medical_record import RecordVersion
    row = (await async_db.execute(
        select(RecordVersion.content).where(
            RecordVersion.medical_record_id == r1.id,
            RecordVersion.version_no == v1,
        )
    )).scalar_one()
    assert row["text"] == "被退回的劣质病历"


@pytest.mark.asyncio
async def test_quick_save_nonexistent_encounter(async_db):
    """不存在的接诊签发 → ValueError。"""
    service = MedicalRecordService(async_db)
    with pytest.raises(ValueError, match="不存在"):
        await service.quick_save("no-such-enc", "outpatient", "x", "doc-x")


def _admit(**kw) -> AdmitPushRequest:
    base = {"visit_id": "V1", "hospital_code": "H1", "patient_name": "王芳",
            "doctor_code": "D1", "birth_date": "1985-03-12"}
    base.update(kw)
    return AdmitPushRequest(**base)


@pytest.mark.asyncio
async def test_his_admit_no_weak_merge_same_name_birthdate(async_db):
    """HIS 链路：同名同生日但无强键 → 建两份档案，绝不误合并。"""
    doc = User(username="D1", password_hash="x", real_name="医生",
               role="doctor", employee_no="D1")
    async_db.add(doc)
    await async_db.commit()

    r1 = await process_admit(async_db, _admit(visit_id="V1"))
    r2 = await process_admit(async_db, _admit(visit_id="V2"))
    # 不同就诊、同名同生日、无身份证 → 必须是两份不同档案
    assert r1.patient_id != r2.patient_id


# ── 第五轮审计修复的回归锁（2026-08-13）────────────────────────────────────
@pytest.mark.asyncio
async def test_completed_encounter_not_reassigned_by_his(async_db):
    """已结束的接诊被 HIS 重推时不改派医生。

    门急诊签发后接诊已 completed、病历也已用原医生名字签发并回写 HIS。
    此时 HIS 若重推（重试/补推/visit_id 复用），原先会把接诊划到另一位医生
    名下——他的"我的接诊"凭空多出陌生病人，而那份病历署的是原医生的名字，
    责任归属直接错乱。
    """
    from app.models.encounter import Encounter

    doc_a = User(username="DA", password_hash="x", real_name="原医生",
                 role="doctor", employee_no="DA")
    doc_b = User(username="DB", password_hash="x", real_name="新医生",
                 role="doctor", employee_no="DB")
    async_db.add_all([doc_a, doc_b])
    await async_db.commit()

    r1 = await process_admit(async_db, _admit(visit_id="VC1", doctor_code="DA"))
    enc = await async_db.get(Encounter, r1.encounter_id)
    assert enc.doctor_id == doc_a.id

    # 医生签发后接诊结束
    enc.status = "completed"
    await async_db.commit()

    # HIS 用另一个工号重推同一 visit_id
    await process_admit(async_db, _admit(visit_id="VC1", doctor_code="DB"))
    await async_db.refresh(enc)
    assert enc.doctor_id == doc_a.id, "已结束的接诊被改派了，责任归属会错乱"


@pytest.mark.asyncio
async def test_in_progress_encounter_still_reassignable(async_db):
    """进行中的接诊仍可改派——不能因为加守卫把正常的转接/交接堵死。"""
    from app.models.encounter import Encounter

    doc_a = User(username="DC", password_hash="x", real_name="医生C",
                 role="doctor", employee_no="DC")
    doc_b = User(username="DD", password_hash="x", real_name="医生D",
                 role="doctor", employee_no="DD")
    async_db.add_all([doc_a, doc_b])
    await async_db.commit()

    r1 = await process_admit(async_db, _admit(visit_id="VP1", doctor_code="DC"))
    enc = await async_db.get(Encounter, r1.encounter_id)
    assert enc.doctor_id == doc_a.id

    await process_admit(async_db, _admit(visit_id="VP1", doctor_code="DD"))
    await async_db.refresh(enc)
    assert enc.doctor_id == doc_b.id, "进行中的接诊应当能正常改派"


@pytest.mark.asyncio
async def test_create_record_rejected_when_already_submitted(async_db):
    """已签发的 (接诊, 病历类型) 不能再建新病历——否则「已签发不可修改」被绕开。"""
    from fastapi import HTTPException

    from app.models.medical_record import MedicalRecord
    from app.schemas.medical_record import MedicalRecordCreate
    from app.services.medical_record_service import MedicalRecordService

    from tests.test_record_safety import _mk_sign_encounter

    eid, doc_id = await _mk_sign_encounter(async_db)
    svc = MedicalRecordService(async_db)
    await svc.quick_save(eid, "outpatient", "主诉：已签发。", doc_id)

    with pytest.raises(HTTPException) as exc:
        await svc.create(MedicalRecordCreate(encounter_id=eid, record_type="outpatient"))
    assert exc.value.status_code == 409

    # 未签发的其他类型仍可正常建
    rec = await svc.create(MedicalRecordCreate(encounter_id=eid, record_type="emergency"))
    assert isinstance(rec, MedicalRecord)


@pytest.mark.asyncio
async def test_resume_requires_same_visit_type(async_db):
    """续接进行中的接诊必须同类型（2026-08-13 第五轮审计修复）。

    原先不比对类型——医生在门诊给某患者建了接诊还没签发，转头去急诊工作台接
    同一位患者会直接续接到那条门诊接诊上：急诊病历落进门诊接诊，质控用门诊
    评分表、回写 HIS 的类型也错。
    """
    from app.models.encounter import Encounter
    from app.models.patient import Patient
    from app.services.encounter_service import EncounterService

    p = Patient(name="续接患者")
    async_db.add(p)
    await async_db.flush()
    doc = User(username="RS1", password_hash="x", real_name="医生", role="doctor")
    async_db.add(doc)
    await async_db.flush()
    enc = Encounter(patient_id=p.id, doctor_id=doc.id, visit_type="outpatient",
                    status="in_progress")
    async_db.add(enc)
    await async_db.commit()

    svc = EncounterService(async_db)
    # 同类型能续接
    assert (await svc.find_in_progress(p.id, doc.id, visit_type="outpatient")) is not None
    # 不同类型不能续接（急诊不该捡到门诊那条）
    assert (await svc.find_in_progress(p.id, doc.id, visit_type="emergency")) is None
    assert (await svc.find_in_progress(p.id, doc.id, visit_type="inpatient")) is None


@pytest.mark.asyncio
async def test_ward_keeps_discharged_pending_record(async_db):
    """已出院但出院记录未签发的接诊仍留在病区列表（2026-08-14 第六轮审计修复）。

    办理出院会把接诊置 completed，而病区列表原先只查 in_progress——接诊当场
    从列表消失。可出院记录按规范是出院后 24 小时内完成，医生这时候已经没有
    任何入口进这个接诊补写了。
    """
    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord
    from app.models.patient import Patient
    from app.services.inpatient_service import list_active_ward

    doc = User(username="WD1", password_hash="x", real_name="住院医生", role="doctor")
    p1 = Patient(name="待补出院记录")
    p2 = Patient(name="已完成出院")
    async_db.add_all([doc, p1, p2])
    await async_db.flush()

    # 甲：已出院、出院记录未签发 → 应保留
    e1 = Encounter(patient_id=p1.id, doctor_id=doc.id, visit_type="inpatient",
                   status="completed")
    # 乙：已出院、出院记录已签发 → 应移出
    e2 = Encounter(patient_id=p2.id, doctor_id=doc.id, visit_type="inpatient",
                   status="completed")
    async_db.add_all([e1, e2])
    await async_db.flush()
    async_db.add(MedicalRecord(encounter_id=e2.id, record_type="discharge_record",
                               status="submitted", current_version=1))
    await async_db.commit()

    items = await list_active_ward(async_db, doc.id)
    ids = {i["encounter_id"] for i in items}
    assert e1.id in ids, "已出院但出院记录未签发的接诊被移出了，医生补写不了"
    assert e2.id not in ids, "出院记录已签发的接诊不该继续占着病区列表"
    got = next(i for i in items if i["encounter_id"] == e1.id)
    assert got["pending_discharge_record"] is True


@pytest.mark.asyncio
async def test_previous_record_excludes_draft_and_cross_type(async_db):
    """带入的「上次病历」必须是已签发 + 同接诊类型（2026-08-14 第六轮审计修复）。

    原查询只按患者过滤，于是带进来的可能是别人未签发的草稿，或者住院接诊
    带入了门诊病历。注释一直写着「最近一次签发病历」，代码里从来没有这个条件。
    """
    from sqlalchemy import desc, select

    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord, RecordVersion
    from app.models.patient import Patient

    doc = User(username="PF1", password_hash="x", real_name="医生", role="doctor")
    pat = Patient(name="复诊患者")
    async_db.add_all([doc, pat])
    await async_db.flush()

    # ① 门诊已签发（跨类型，不该被住院接诊带入）
    e_out = Encounter(patient_id=pat.id, doctor_id=doc.id, visit_type="outpatient",
                      status="completed")
    # ② 住院未签发草稿（不该被带入）
    e_draft = Encounter(patient_id=pat.id, doctor_id=doc.id, visit_type="inpatient",
                        status="in_progress")
    # ③ 住院已签发（这才是应该带入的）
    e_ok = Encounter(patient_id=pat.id, doctor_id=doc.id, visit_type="inpatient",
                     status="completed")
    async_db.add_all([e_out, e_draft, e_ok])
    await async_db.flush()

    for enc, status, text in [
        (e_out, "submitted", "门诊病历正文"),
        (e_draft, "draft", "别人的草稿"),
        (e_ok, "submitted", "住院已签发正文"),
    ]:
        rec = MedicalRecord(encounter_id=enc.id, record_type="admission_note",
                            status=status, current_version=1)
        async_db.add(rec)
        await async_db.flush()
        async_db.add(RecordVersion(medical_record_id=rec.id, version_no=1,
                                   content={"text": text}, source="doctor_signed"))
    await async_db.commit()

    # 模拟 quick-start 里带入上次病历的查询（住院、排除当前接诊）
    row = (await async_db.execute(
        select(RecordVersion.content)
        .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
        .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
        .where(
            Encounter.patient_id == pat.id,
            Encounter.visit_type == "inpatient",
            MedicalRecord.status == "submitted",
            RecordVersion.content.isnot(None),
        )
        .order_by(desc(RecordVersion.created_at))
        .limit(1)
    )).scalar_one_or_none()

    text = (row or {}).get("text")
    assert text == "住院已签发正文", f"带入了不该带的内容：{text}"


@pytest.mark.asyncio
async def test_compliance_ignores_unsigned_draft(async_db):
    """住院时效合规只认已签发文书，空白草稿不算完成（2026-08-14 第六轮审计修复）。

    原先不过滤 status——AI 一生成就建了 MedicalRecord 行，医生什么都没写，
    合规面板却显示「入院记录已完成」，而这个面板正是给医生和质控看
    「还有哪些文书没写」的。
    """
    from datetime import datetime, timedelta

    from httpx import ASGITransport, AsyncClient

    from app.core.security import get_current_user
    from app.database import get_db
    from app.main import app
    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord
    from app.models.patient import Patient

    doc = User(username="CP1", password_hash="x", real_name="住院医生", role="doctor")
    pat = Patient(name="合规测试患者")
    async_db.add_all([doc, pat])
    await async_db.flush()
    enc = Encounter(patient_id=pat.id, doctor_id=doc.id, visit_type="inpatient",
                    status="in_progress", visited_at=datetime.now() - timedelta(hours=2))
    async_db.add(enc)
    await async_db.flush()
    # 只有草稿，没签发
    async_db.add(MedicalRecord(encounter_id=enc.id, record_type="admission_note",
                               status="draft", current_version=1))
    await async_db.commit()

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: doc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.get(f"/api/v1/encounters/{enc.id}/compliance")
        assert res.status_code == 200
        items = {i["record_type"]: i for i in res.json()["items"]}
        adm = items.get("admission_note")
        assert adm is not None
        assert adm["status"] != "done", "空白草稿被当成已完成了"
        assert adm["done_at"] is None
    finally:
        app.dependency_overrides.clear()
