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
    # 唯一后缀用 uuid 而非 id(p)（2026-08-12 修 CI 间歇性失败）：id() 是内存地址，
    # 上一次调用的对象被回收后，下一次分配可能复用同一地址 → 同名用户撞
    # UNIQUE 约束，是否触发取决于分配器行为，表现为随机红。
    from uuid import uuid4
    suffix = uuid4().hex[:8]
    p = Patient(name="对账患者")
    db.add(p)
    doc = User(username=f"d{suffix}", password_hash="x", real_name="医生", role="doctor")
    db.add(doc)
    await db.flush()
    # 2026-08-29 粒度下沉：对账判定改读文书级 writeback_records[type:no]，
    # 夹具跟着把状态落到文书键上（record_no 模型默认 1 → 键尾恒 "1"）
    wb = None
    if writeback_status is not None:
        wb = {"status": writeback_status, "reconcile_attempts": attempts}
        if exhausted:
            wb["reconcile_exhausted"] = True
    enc = Encounter(
        patient_id=p.id, doctor_id=doc.id, visit_type="outpatient",
        visit_no=f"V{suffix}", status="in_progress",
        visited_at=visited or datetime.now(),
        his_external_ref={"source": "admit_push", "hospital_code": "H1",
                          **({"writeback_records": {"outpatient:1": wb}} if wb else {})},
    )
    db.add(enc)
    await db.flush()
    if submitted:
        # submitted_at 必须给（2026-08-14）：真实签发一定会写它，而对账窗口现在
        # 按签发时间筛（原先按接诊开始时间，住院中后期签发的会被漏掉）。
        # 夹具不设这个字段等于造了一份现实中不存在的数据。
        db.add(MedicalRecord(encounter_id=enc.id, record_type="outpatient",
                             status="submitted",
                             submitted_at=visited or datetime.now()))
    await db.commit()
    return enc.id


@pytest.mark.asyncio
async def test_reconcile_finds_failed_writeback(async_db):
    """已签发但回写 write_failed 的 HIS 接诊被列为对账候选。"""
    from app.his_adapter.writeback_reconcile import _find_candidates
    eid = await _mk_his_encounter(async_db, writeback_status="write_failed")
    cands = await _find_candidates(async_db)
    assert eid in [e.id for e, _rec in cands]


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
async def test_reconcile_masked_failure_still_candidate(async_db):
    """住院多文书：后一份的 success 不得掩盖前一份的失败（2026-08-29 粒度下沉回归锁）。

    粒度下沉前状态是接诊级一份：病程#3 write_failed 被 #4 的 success 覆写后，
    对账永远看不到 #3，HIS 病案静默缺一份。现在逐文书判定，
    失败的那份必须仍是候选。
    """
    from app.his_adapter.writeback_reconcile import _find_candidates
    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord
    from app.models.patient import Patient
    from app.models.user import User
    from uuid import uuid4
    suffix = uuid4().hex[:8]
    p = Patient(name="多文书患者")
    doc = User(username=f"m{suffix}", password_hash="x", real_name="医生", role="doctor")
    async_db.add_all([p, doc])
    await async_db.flush()
    enc = Encounter(
        patient_id=p.id, doctor_id=doc.id, visit_type="inpatient",
        visit_no=f"V{suffix}", status="in_progress", visited_at=datetime.now(),
        his_external_ref={
            "source": "admit_push", "hospital_code": "H1",
            # 病程 #3 失败、#4 成功——各自独立状态
            "writeback_records": {
                "course_record:3": {"status": "write_failed", "reconcile_attempts": 0},
                "course_record:4": {"status": "success"},
            },
            # 接诊级旧摘要是最后一次（成功）——它不得参与对账判定
            "writeback": {"status": "success"},
        },
    )
    async_db.add(enc)
    await async_db.flush()
    for no in (3, 4):
        async_db.add(MedicalRecord(
            encounter_id=enc.id, record_type="course_record", record_no=no,
            status="submitted", submitted_at=datetime.now(),
        ))
    await async_db.commit()

    cands = await _find_candidates(async_db)
    mine = [(e.id, _r.record_no) for e, _r in cands if e.id == enc.id]
    assert (enc.id, 3) in mine, "失败的 #3 被后续成功掩盖，未列为对账候选"
    assert (enc.id, 4) not in mine, "已成功的 #4 不该重投"


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


@pytest.mark.asyncio
async def test_reconcile_attempts_accumulate_across_rounds(async_db, monkeypatch):
    """多轮对账的重投次数必须真实累加（2026-08-13 复检修复的回归锁）。

    修复前每轮 send_writeback 会把 reconcile_attempts 抹零、_mark_reconcile 再 +1，
    计数恒为 1 → MAX_RECONCILE_ATTEMPTS 上限永不成立 → 耗尽告警永不触发、
    失败回写被无限静默重投。
    """
    import app.database as _db
    from app.his_adapter import writeback_reconcile as wr

    eid = await _mk_his_encounter(async_db, writeback_status="write_failed")

    # 让每轮对账都走真实的 send_writeback（未配回写地址 → skipped，属可重试状态），
    # 且各轮共用同一个测试会话，避免 SQLite 内存库跨 session 不可见。
    # reconcile_once 内部是 `from app.database import AsyncSessionLocal`，故 patch 源模块。
    monkeypatch.setattr(_db, "AsyncSessionLocal", lambda: _SessionCtx(async_db))

    for expected in (1, 2, 3):
        await wr.reconcile_once()
        enc = await async_db.get(Encounter_model(), eid)
        await async_db.refresh(enc)
        wb = enc.his_external_ref["writeback_records"]["outpatient:1"]
        assert wb["reconcile_attempts"] == expected, (
            f"第 {expected} 轮后计数应为 {expected}，实际 {wb.get('reconcile_attempts')}"
            "——回写落库又把对账计数抹掉了")


def Encounter_model():
    """延迟取 Encounter 模型（本文件的 import 都在函数内，保持风格一致）。"""
    from app.models.encounter import Encounter
    return Encounter


class _SessionCtx:
    """把既有 async session 包成 `async with AsyncSessionLocal() as db` 的形状。

    对账代码每步都新开会话（生产是真实连接池）；单测里 SQLite 内存库跨会话
    不可见，故复用测试会话，退出时不关闭。
    """

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


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


async def _mk_sign_encounter(db, visit_type: str = "outpatient"):
    from app.models.encounter import Encounter
    from app.models.patient import Patient
    from app.models.user import User
    # 同 _mk_his_encounter：唯一后缀用 uuid，杜绝 id() 内存地址复用撞唯一约束
    from uuid import uuid4
    p = Patient(name="签名患者")
    db.add(p)
    doc = User(username=f"sd{uuid4().hex[:8]}", password_hash="x", real_name="签名医生",
               role="doctor")
    db.add(doc)
    await db.flush()
    enc = Encounter(patient_id=p.id, doctor_id=doc.id, visit_type=visit_type,
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


# ── 第五轮审计修复的回归锁：链接校验（2026-08-13）──────────────────────────
@pytest.mark.asyncio
async def test_deleted_middle_version_detected(async_db):
    """删掉链中一环能被检出——模块注释一直这么承诺，但此前做不到。

    原实现的 verify_version 只做单行自校验：把该行自己存的 prev_hash 当哈希输入
    重算，从不查这个 prev_hash 是否真对应链上某一环。于是删中间版本零痕迹。
    """
    from sqlalchemy import select

    from app.models.medical_record import RecordVersion
    from app.services._record_signature import verify_chain
    from app.services.medical_record_service import MedicalRecordService

    svc = MedicalRecordService(async_db)
    # 连签三份病历，构成一条三环的链
    for i in range(3):
        eid, doc_id = await _mk_sign_encounter(async_db)
        await svc.quick_save(eid, "outpatient", f"主诉：链条测试{i}。", doc_id)

    assert await verify_chain(async_db) == [], "刚签发的链本应完好"

    # 删掉中间那一环（模拟有库权限的人抹掉一份病历）
    signed = (await async_db.execute(
        select(RecordVersion).where(RecordVersion.sign_hash.isnot(None))
        .order_by(RecordVersion.created_at)
    )).scalars().all()
    assert len(signed) >= 3
    await async_db.delete(signed[1])
    await async_db.commit()

    issues = await verify_chain(async_db)
    assert issues, "删掉链中一环没有被检出——链接校验又失效了"
    assert any("链断裂" in i["issue"] for i in issues)


@pytest.mark.asyncio
async def test_recomputed_hash_after_edit_detected(async_db):
    """改正文后按同一 prev_hash 重算 sign_hash 也能被检出。

    哈希算法无密钥且就在仓库里，攻击者完全可以改完正文自行重算——单行自校验
    会通过，只有链接校验能发现后继环的 prev_hash 已经悬空。
    """
    from sqlalchemy import select

    from app.models.medical_record import RecordVersion
    from app.services._record_signature import compute_sign_hash, verify_chain
    from app.services.medical_record_service import MedicalRecordService

    svc = MedicalRecordService(async_db)
    recs = []
    for i in range(2):
        eid, doc_id = await _mk_sign_encounter(async_db)
        recs.append(await svc.quick_save(eid, "outpatient", f"主诉：重算测试{i}。", doc_id))

    signed = (await async_db.execute(
        select(RecordVersion).where(RecordVersion.sign_hash.isnot(None))
        .order_by(RecordVersion.created_at)
    )).scalars().all()
    victim = signed[0]          # 被改的那一环，后面还有一环引用它

    # 攻击者：改正文 + 用同一 prev_hash 重算哈希，让单行自校验通过
    from app.models.medical_record import MedicalRecord
    rec = await async_db.get(MedicalRecord, victim.medical_record_id)
    victim.content = {"text": "主诉：伪造的正文。"}
    victim.sign_hash = compute_sign_hash(
        content_text="主诉：伪造的正文。",
        patient_snapshot=rec.patient_snapshot,
        doctor_id=victim.triggered_by or "",
        submitted_at_iso=rec.submitted_at.isoformat() if rec.submitted_at else "",
        prev_hash=victim.prev_hash or "0" * 64,
    )
    await async_db.commit()

    issues = await verify_chain(async_db)
    assert issues, "改正文后重算哈希没有被检出——这正是无密钥哈希的攻击方式"


@pytest.mark.asyncio
async def test_inpatient_resign_keeps_first_submitted_at(async_db):
    """住院二次签发不覆盖首签时间与患者快照，历史版本的哈希继续成立。

    sign_hash 是版本级的，但 submitted_at / patient_snapshot 是 record 级的。
    原先每次签发都覆写，导致此前所有签发版本复算必然对不上，被永久误报为
    「已篡改」，且第一份文书的法定签发时刻被抹掉无从追溯。
    """
    from app.models.medical_record import MedicalRecord
    from app.services._record_signature import verify_chain
    from app.services.medical_record_service import MedicalRecordService

    eid, doc_id = await _mk_sign_encounter(async_db, visit_type="inpatient")
    svc = MedicalRecordService(async_db)
    rec = await svc.quick_save(eid, "admission_note", "入院记录：第一版。", doc_id)
    first_submitted = (await async_db.get(MedicalRecord, rec.id)).submitted_at
    assert first_submitted is not None

    # 住院允许对同一 record_type 再次签发
    await svc.quick_save(eid, "admission_note", "入院记录：第二版。", doc_id)

    after = await async_db.get(MedicalRecord, rec.id)
    assert after.submitted_at == first_submitted, "首次签发时间被覆盖了"
    assert await verify_chain(async_db) == [], "二次签发把历史版本判成了篡改"


@pytest.mark.asyncio
async def test_his_offline_alerts_but_never_abandons(async_db, monkeypatch):
    """HIS 整体离线时告警但不放弃回写（2026-08-13 第五轮审计修复）。

    skipped 的含义是「WS 与 HTTP 都不在线」= HIS 侧整体离线，跟「推过去失败了」
    是两回事。原先它也触发 exhausted，于是 HIS 停机半小时就把全院当天病历统统
    标记成永久放弃——等 HIS 恢复也不会补推，而这正是对账存在的全部意义。
    """
    import app.database as _db
    from app.his_adapter import writeback_reconcile as wr

    eid = await _mk_his_encounter(async_db, writeback_status="write_failed")
    monkeypatch.setattr(_db, "AsyncSessionLocal", lambda: _SessionCtx(async_db))

    # 跑到远超上限的轮数（未配回写地址 → 每轮都是 skipped）
    for _ in range(wr.MAX_RECONCILE_ATTEMPTS + 3):
        await wr.reconcile_once()

    enc = await async_db.get(Encounter_model(), eid)
    await async_db.refresh(enc)
    wb = (enc.his_external_ref or {}).get("writeback") or {}
    assert not wb.get("reconcile_exhausted"), (
        "HIS 离线被判成永久放弃了——恢复后这些病历再也不会补推"
    )


# ── 第六轮审计修复的回归锁（2026-08-14）────────────────────────────────────
def test_emergency_record_can_pass_qc():
    """填写完整的急诊病历必须能通过质控——否则急诊医生根本签发不了病历。

    原缺陷：中医四诊/中医诊断/治则治法等**中医门诊专属**规则没有急诊判别，
    而急诊模板压根不渲染这些子行 → 必然扣满 体格检查/诊断/治疗意见 三个大项
    上限、总分恒 70 不合格 → 前端 canSubmit 带 qcPass !== false 条件 →
    签发按钮永久置灰，且模板里没有这些章节可补，医生无法自救。
    """
    from app.services.ai._render_visit import render_emergency
    from app.services.qc_engine.checker import build_context
    from app.services.qc_engine.rubrics.zj_outpatient_emergency_2023 import (
        ZJ_OUTPATIENT_EMERGENCY_V2023,
    )
    from app.services.qc_engine.scorer import score

    text = render_emergency(
        {
            "chief_complaint": "胸痛3小时",
            "history_present_illness": "3小时前活动后突发胸骨后压榨样疼痛",
            "past_history": "高血压10年",
            "allergy_history": "否认药物食物过敏",
            "physical_exam_vitals": "T:36.8℃ P:98次/分 R:20次/分 BP:150/95mmHg",
            "physical_exam_text": "急性痛苦面容，双肺呼吸音清，心律齐",
            "auxiliary_exam": "心电图示ST段抬高",
            "diagnosis": "急性ST段抬高型心肌梗死",
            "treatment_plan": "心电监护、吸氧、阿司匹林负荷量，急诊PCI",
            "patient_disposition": "收住心内科CCU",
        },
        visit_time="2026-08-14 09:00",
        onset_time="2026-08-14 06:00",
    )
    rep = score(ZJ_OUTPATIENT_EMERGENCY_V2023, build_context(text, record_type="emergency"))
    assert rep.passed, f"急诊病历质控不通过（{rep.score} 分），医生将无法签发"


def test_admission_note_renders_allergy_history():
    """入院记录必须渲染过敏史——schema 里有、LLM 会返回，原先渲染时被静默丢弃。

    过敏史缺失是直接用药安全问题，且门诊/急诊渲染都有这一行，明确是漏写。
    """
    from app.services.ai._render_visit import render_admission_note

    text = render_admission_note(
        {"chief_complaint": "主诉", "allergy_history": "青霉素过敏（皮试阳性）"},
        patient_gender="男",
    )
    assert "【过敏史】" in text and "青霉素" in text


def test_vitals_guard_covers_inpatient_course_field():
    """住院病程/术后记录的查体字段也必须受数值守卫保护。

    physical_exam_today 的 schema 描述直接要求 LLM 输出 T/P/R/BP，
    漏掉它等于住院这条最高频文书路径上守卫完全没装，AI 编的体征直接进病历。
    """
    from app.services.ai.record_gen_v2_service import _VITALS_GUARDED_FIELDS

    assert "physical_exam_today" in _VITALS_GUARDED_FIELDS


@pytest.mark.asyncio
async def test_inpatient_second_course_record_does_not_overwrite_first(async_db):
    """住院第二份同类型文书新起一份，不覆盖第一份（2026-08-14 第六轮审计修复）。

    住院一次接诊天然有多份日常病程/查房记录。原先只按 (encounter_id, record_type)
    取最近更新的一行来写，第二份直接覆盖第一份——医生前一天写的病程被顶掉，
    内容永久丢失。
    """
    from sqlalchemy import select

    from app.models.medical_record import MedicalRecord
    from app.services.medical_record_service import MedicalRecordService

    eid, doc_id = await _mk_sign_encounter(async_db, visit_type="inpatient")
    svc = MedicalRecordService(async_db)
    await svc.quick_save(eid, "course_record", "病程一：患者诉腰痛缓解。", doc_id)
    await svc.quick_save(eid, "course_record", "病程二：今日查房，切口愈合good。", doc_id)

    rows = (await async_db.execute(
        select(MedicalRecord).where(
            MedicalRecord.encounter_id == eid,
            MedicalRecord.record_type == "course_record",
        ).order_by(MedicalRecord.record_no)
    )).scalars().all()

    assert len(rows) == 2, f"住院第二份病程没有新建，仍然只有 {len(rows)} 份（第一份被覆盖了）"
    assert [r.record_no for r in rows] == [1, 2]


@pytest.mark.asyncio
async def test_discharge_record_timeliness_counts_from_discharge(async_db):
    """出院记录时效从**出院**时刻起算，不是入院（2026-08-14 第六轮审计修复）。

    原先所有类型统一用 submitted_at - visited_at，住院半个月的病人出院记录必然
    被判超时，达标率被系统性压低、指标失去意义。
    """
    from datetime import datetime, timedelta
    from uuid import uuid4

    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord
    from app.models.patient import Patient
    from app.models.user import User as U
    from app.services.admin_stats_service import get_quality_health

    doc = U(username=f"tl{uuid4().hex[:6]}", password_hash="x", real_name="医生", role="doctor")
    pat = Patient(name="长住院患者")
    async_db.add_all([doc, pat])
    await async_db.flush()

    now = datetime.now()
    # 住院 15 天，出院后 2 小时签发出院记录 → 应判达标
    enc = Encounter(
        patient_id=pat.id, doctor_id=doc.id, visit_type="inpatient", status="completed",
        visited_at=now - timedelta(days=15), completed_at=now - timedelta(hours=2),
    )
    async_db.add(enc)
    await async_db.flush()
    async_db.add(MedicalRecord(
        encounter_id=enc.id, record_type="discharge_record", status="submitted",
        current_version=1, submitted_at=now,
    ))
    await async_db.commit()

    res = await get_quality_health(async_db, days=30)
    tl = res.get("timeliness") or {}
    dr = tl.get("discharge_record")
    assert dr is not None, f"出院记录未纳入时效统计：{tl}"
    assert dr["on_time"] == dr["total"] == 1, (
        f"出院后 2 小时签发却被判超时（说明还在用入院时刻起算）：{dr}"
    )


@pytest.mark.asyncio
async def test_reconcile_covers_late_signed_inpatient_record(async_db):
    """住院中后期签发的病历也要能被对账扫到（2026-08-14 第六轮审计修复）。

    原窗口条件是「接诊**开始**于 3 天内」。门急诊当天接诊当天签发没问题，
    但住院一次接诊长达十几天——病人第 5 天签发的病程，接诊早已在窗口外，
    对账根本扫不到它，回写失败后永远不重投也不告警。
    """
    from datetime import datetime, timedelta
    from uuid import uuid4

    from app.his_adapter.writeback_reconcile import _find_candidates
    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord
    from app.models.patient import Patient
    from app.models.user import User as U

    suffix = uuid4().hex[:8]
    pat = Patient(name="长住院患者")
    doc = U(username=f"lr{suffix}", password_hash="x", real_name="医生", role="doctor")
    async_db.add_all([pat, doc])
    await async_db.flush()

    now = datetime.now()
    # 接诊 10 天前开始（远在 3 天窗口外），但病历是刚刚签发的
    enc = Encounter(
        patient_id=pat.id, doctor_id=doc.id, visit_type="inpatient",
        visit_no=f"V{suffix}", status="in_progress",
        visited_at=now - timedelta(days=10),
        his_external_ref={"source": "admit_push", "hospital_code": "H1",
                          "writeback_records": {"course_record:1": {
                              "status": "write_failed", "reconcile_attempts": 0}}},
    )
    async_db.add(enc)
    await async_db.flush()
    async_db.add(MedicalRecord(
        encounter_id=enc.id, record_type="course_record", status="submitted",
        current_version=1, submitted_at=now - timedelta(hours=1),
    ))
    await async_db.commit()

    cands = await _find_candidates(async_db)
    assert enc.id in [e.id for e, _rec in cands], (
        "住院中后期签发的病历没被对账扫到——回写失败会永远不重投"
    )


@pytest.mark.asyncio
async def test_inpatient_each_document_has_own_submitted_at(async_db):
    """住院每份文书有独立的签发时间，回写才能选中最新签发的那份。

    第六轮审计报「住院同类型文书的 submitted_at 只写一次，导致当天签发的病程
    回写不到 HIS」。该问题的前提是"多份文书共用一行"，而 record_no 修复后每份
    文书是独立的行、各有自己的 submitted_at——这条测试锁住这个前提不被改回去。
    """
    from sqlalchemy import select

    from app.models.medical_record import MedicalRecord
    from app.services.medical_record_service import MedicalRecordService

    eid, doc_id = await _mk_sign_encounter(async_db, visit_type="inpatient")
    svc = MedicalRecordService(async_db)
    await svc.quick_save(eid, "course_record", "病程一。", doc_id)
    await svc.quick_save(eid, "course_record", "病程二。", doc_id)

    rows = (await async_db.execute(
        select(MedicalRecord).where(
            MedicalRecord.encounter_id == eid,
            MedicalRecord.record_type == "course_record",
        ).order_by(MedicalRecord.record_no)
    )).scalars().all()

    assert len(rows) == 2
    assert all(r.submitted_at is not None for r in rows), "有文书没有签发时间"
    # 回写按 (已签发, submitted_at desc) 排序，能选中最新签发的那份
    assert rows[1].submitted_at >= rows[0].submitted_at
