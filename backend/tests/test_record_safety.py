"""病历安全批次测试（2026-08-11）：主生成数值守卫 + 回写对账 + 配置校验 + 深度健康检查。"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.ai.record_gen_v2_service import _guard_vitals_in_result


# ── #2 主生成路径数值守卫 ──────────────────────────────────────────────

def test_guard_strips_fabricated_vitals():
    """医生没录体征，AI 编造的生命体征行被整段剔除。"""
    req = SimpleNamespace(temperature="", pulse="", physical_exam="腹软无压痛",
                          chief_complaint="腹痛3天", history_present_illness="")
    result = {"physical_exam_vitals": "T:36.5℃ P:80次/分 BP:120/80mmHg",
              "physical_exam_text": "腹软无压痛"}
    _guard_vitals_in_result(result, req)
    assert result["physical_exam_vitals"] == ""  # 数值无出处 → 剔空
    assert result["physical_exam_text"] == "腹软无压痛"  # 无数值文字保留


def test_guard_keeps_doctor_entered_vitals():
    """医生真实录入的体征（出现在 source 里）不被误删。"""
    req = SimpleNamespace(temperature="36.5", pulse="80", bp_systolic="120",
                          bp_diastolic="80", physical_exam="", chief_complaint="",
                          history_present_illness="")
    result = {"physical_exam_vitals": "T:36.5℃ P:80次/分 BP:120/80mmHg"}
    _guard_vitals_in_result(result, req)
    assert "36.5" in result["physical_exam_vitals"]  # 有出处 → 保留


def test_guard_noop_on_non_dict():
    """result 非 dict 时安全空跑。"""
    _guard_vitals_in_result("not a dict", SimpleNamespace())  # 不抛异常即可


# ── #5 配置启动校验 ─────────────────────────────────────────────────────

def test_validate_runtime_production_raises_without_creds():
    """生产环境 HIS 开关开但缺凭证 → 抛错阻断启动。"""
    from app.config import Settings
    s = Settings(app_env="production", his_adapter_enabled=True,
                 his_inbound_app_id="", his_inbound_app_secret="",
                 secret_key="x", orthanc_password="x")
    with pytest.raises(ValueError, match="缺少入站验签凭证"):
        s.validate_runtime()


def test_validate_runtime_dev_only_warns():
    """开发环境同样配置只告警不抛（不阻断本地联调）。"""
    from app.config import Settings
    s = Settings(app_env="development", his_adapter_enabled=True,
                 his_inbound_app_id="", his_inbound_app_secret="",
                 secret_key="x", orthanc_password="x")
    s.validate_runtime()  # 不抛异常


def test_validate_runtime_ok_with_creds():
    """凭证齐全 → 通过。"""
    from app.config import Settings
    s = Settings(app_env="production", his_adapter_enabled=True,
                 his_inbound_app_id="app", his_inbound_app_secret="sec",
                 secret_key="x", orthanc_password="x")
    s.validate_runtime()


# ── #1 回写对账 ─────────────────────────────────────────────────────────

async def _mk_his_encounter(db, *, writeback_status, submitted=True, exhausted=False,
                            attempts=0, visited=None):
    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord
    from app.models.patient import Patient
    from app.models.user import User
    p = Patient(name="对账患者")
    db.add(p)
    doc = User(username=f"d{id(p)%10000}", password_hash="x", real_name="医生", role="doctor")
    db.add(doc)
    await db.flush()
    wb = None
    if writeback_status is not None:
        wb = {"status": writeback_status, "reconcile_attempts": attempts}
        if exhausted:
            wb["reconcile_exhausted"] = True
    enc = Encounter(
        patient_id=p.id, doctor_id=doc.id, visit_type="outpatient",
        visit_no=f"V{id(p)%100000}", status="in_progress",
        visited_at=visited or datetime.now(),
        his_external_ref={"source": "admit_push", "hospital_code": "H1",
                          **({"writeback": wb} if wb else {})},
    )
    db.add(enc)
    await db.flush()
    if submitted:
        db.add(MedicalRecord(encounter_id=enc.id, record_type="outpatient",
                             status="submitted"))
    await db.commit()
    return enc.id


@pytest.mark.asyncio
async def test_reconcile_finds_failed_writeback(async_db):
    """已签发但回写 write_failed 的 HIS 接诊被列为对账候选。"""
    from app.his_adapter.writeback_reconcile import _find_candidates
    eid = await _mk_his_encounter(async_db, writeback_status="write_failed")
    cands = await _find_candidates(async_db)
    assert eid in [c.id for c in cands]


@pytest.mark.asyncio
async def test_reconcile_skips_success(async_db):
    """回写已 success 的不再对账。"""
    from app.his_adapter.writeback_reconcile import _find_candidates
    await _mk_his_encounter(async_db, writeback_status="success")
    assert await _find_candidates(async_db) == []


@pytest.mark.asyncio
async def test_reconcile_skips_exhausted(async_db):
    """已标记 reconcile_exhausted 的不再对账（避免刷屏重投）。"""
    from app.his_adapter.writeback_reconcile import _find_candidates
    await _mk_his_encounter(async_db, writeback_status="write_failed", exhausted=True)
    assert await _find_candidates(async_db) == []


@pytest.mark.asyncio
async def test_reconcile_skips_non_submitted(async_db):
    """未签发的接诊（还没到回写环节）不对账。"""
    from app.his_adapter.writeback_reconcile import _find_candidates
    await _mk_his_encounter(async_db, writeback_status=None, submitted=False)
    assert await _find_candidates(async_db) == []


@pytest.mark.asyncio
async def test_reconcile_skips_old_window(async_db):
    """超出对账时间窗（3天前）的不处理。"""
    from app.his_adapter.writeback_reconcile import _find_candidates
    await _mk_his_encounter(async_db, writeback_status="write_failed",
                            visited=datetime.now() - timedelta(days=5))
    assert await _find_candidates(async_db) == []


# ── A批 电子签名防篡改哈希链 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_sign_hash_computed_and_verifies(async_db):
    """签发后版本带 sign_hash，且 verify_version 判定未篡改。"""
    from app.models.medical_record import RecordVersion
    from app.services._record_signature import verify_version
    from app.services.medical_record_service import MedicalRecordService
    from sqlalchemy import select

    eid, doc_id = await _mk_sign_encounter(async_db)
    svc = MedicalRecordService(async_db)
    rec = await svc.quick_save(eid, "outpatient", "主诉：签名测试。", doc_id)
    ver = (await async_db.execute(
        select(RecordVersion).where(RecordVersion.medical_record_id == rec.id,
                                    RecordVersion.version_no == rec.current_version)
    )).scalar_one()
    assert ver.sign_hash and len(ver.sign_hash) == 64
    assert await verify_version(async_db, ver) is True


@pytest.mark.asyncio
async def test_tampered_content_detected(async_db):
    """库内直接改已签发版本正文 → verify 报篡改。"""
    from app.models.medical_record import RecordVersion
    from app.services._record_signature import verify_version
    from app.services.medical_record_service import MedicalRecordService
    from sqlalchemy import select

    eid, doc_id = await _mk_sign_encounter(async_db)
    svc = MedicalRecordService(async_db)
    rec = await svc.quick_save(eid, "outpatient", "主诉：原始内容。", doc_id)
    ver = (await async_db.execute(
        select(RecordVersion).where(RecordVersion.medical_record_id == rec.id,
                                    RecordVersion.version_no == rec.current_version)
    )).scalar_one()
    # 模拟库内篡改：绕过签发直接改正文
    ver.content = {"text": "主诉：被偷偷改过的内容。"}
    await async_db.commit()
    assert await verify_version(async_db, ver) is False


async def _mk_sign_encounter(db):
    from app.models.encounter import Encounter
    from app.models.patient import Patient
    from app.models.user import User
    p = Patient(name="签名患者")
    db.add(p)
    doc = User(username=f"sd{id(p)%10000}", password_hash="x", real_name="签名医生",
               role="doctor")
    db.add(doc)
    await db.flush()
    enc = Encounter(patient_id=p.id, doctor_id=doc.id, visit_type="outpatient",
                    status="in_progress")
    db.add(enc)
    await db.commit()
    await db.refresh(enc)
    return enc.id, doc.id


# ── B批 质量健康度看板 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quality_health_aggregates(async_db):
    """回写成功率/时效达标率聚合正确。"""
    from app.services.admin_stats_service import get_quality_health
    # 造 2 条 HIS 接诊：一条回写 success，一条 write_failed
    await _mk_his_encounter(async_db, writeback_status="success")
    await _mk_his_encounter(async_db, writeback_status="write_failed")
    health = await get_quality_health(async_db)
    wb = health["writeback"]
    assert wb["total"] == 2 and wb["success"] == 1
    assert wb["success_rate"] == 0.5
    assert "feedback" in health and "timeliness" in health
