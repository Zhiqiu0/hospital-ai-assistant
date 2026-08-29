"""路由级归属校验回归（IDOR 修复）

背景：core/authz.py 里的 assert_encounter_access 等守卫早就写好并
在 PACS 用对了，但 patients.py / encounters.py / medical_records.py 的一批端点当时
「漏挂」——单元测试只测了 helper 本身，没测「路由是否真的调用了 helper」，导致越权
（医生能读任意患者身份证号/PHI）在真实请求里长期存在。本文件用 HTTP 级请求覆盖这条
「路由确实挂了校验」的契约，防止再退化。

覆盖：
  - 非接诊医生访问他人患者详情/档案 → 403；对自己接诊过的患者 → 200
  - 非接诊医生访问他人接诊详情 / previous-record → 403
  - 病历 quick_save / auto_save_draft 越权 → 403
"""
from datetime import date, datetime
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import get_current_user
from app.database import get_db
from app.main import app
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User


def _override_user(uid: str, role: str = "doctor"):
    """返回一个能被 get_current_user 覆盖使用的假用户（authz 只读 id/role）。"""
    return User(id=uid, username=f"u_{uid}", password_hash="x", real_name="测试", role=role, is_active=True)


@pytest_asyncio.fixture
async def seeded(async_db):
    """建两个患者：一个 doc-me 接诊过（own），一个只有 doc-other 接诊过（other）。"""
    own = Patient(id="pat-own", name="我的患者", birth_date=date(1970, 1, 1))
    other = Patient(id="pat-other", name="他人患者", birth_date=date(1980, 1, 1))
    async_db.add_all([own, other])
    await async_db.commit()

    enc_own = Encounter(
        id="enc-own", patient_id=own.id, doctor_id="doc-me",
        visit_type="outpatient", status="in_progress", visited_at=datetime(2026, 4, 1),
    )
    enc_other = Encounter(
        id="enc-other", patient_id=other.id, doctor_id="doc-other",
        visit_type="outpatient", status="in_progress", visited_at=datetime(2026, 4, 1),
    )
    async_db.add_all([enc_own, enc_other])
    await async_db.commit()
    return {"own": own, "other": other, "enc_own": enc_own, "enc_other": enc_other}


@pytest_asyncio.fixture
async def client_doc_me(async_db, seeded) -> AsyncGenerator[AsyncClient, None]:
    """以 doc-me 身份发请求（他接诊过 pat-own，没接诊过 pat-other）。"""
    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[get_current_user] = lambda: _override_user("doc-me")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_patient_detail_read_open_to_any_doctor(client_doc_me):
    """医生读没接诊过的患者详情 → 200（2026-08-13 放开读，靠审计追责）。

    身份证/住址等敏感字段不靠拦截保护，靠"每次查阅写审计"——admin 在操作
    日志页可追溯谁何时看了谁。写入仍受归属保护（见下条）。
    """
    r = await client_doc_me.get("/api/v1/patients/pat-other")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_patient_profile_read_open_to_any_doctor(client_doc_me):
    """医生读没接诊过的患者档案 → 200（2026-08-13 与已签发病历同口径放开）。

    过敏史/既往史从 /medical-records/by-patient 本就对全院开放，拦档案读挡不住
    信息，只会让代班/复诊换医生时看不到开药前最该看的结构化过敏史。
    """
    r = await client_doc_me.get("/api/v1/patients/pat-other/profile")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_patient_detail_write_still_blocked(client_doc_me):
    """读放开了，写没放开：改别人接诊的患者基本信息仍 403。"""
    r = await client_doc_me.put("/api/v1/patients/pat-other", json={"name": "越权改"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cross_doctor_read_writes_audit(client_doc_me, async_db, patched_audit_session):
    """跨医生读患者详情必须留痕——放开归属后，审计是唯一的追责手段。"""
    from sqlalchemy import select

    from app.models.audit_log import AuditLog

    r = await client_doc_me.get("/api/v1/patients/pat-other")
    assert r.status_code == 200
    rows = (await async_db.execute(
        select(AuditLog).where(
            AuditLog.action == "view_patient", AuditLog.resource_id == "pat-other"
        )
    )).scalars().all()
    assert rows, "跨医生读患者详情没写审计日志"


@pytest.mark.asyncio
async def test_patient_profile_write_still_blocked(client_doc_me):
    """但写档案仍受归属保护——过敏史被改错是临床风险，留一道门槛。"""
    r = await client_doc_me.put(
        "/api/v1/patients/pat-other/profile", json={"allergy_history": "越权改"}
    )
    assert r.status_code == 403
    r = await client_doc_me.post(
        "/api/v1/patients/pat-other/profile/confirm", json={"field": "allergy_history"}
    )
    assert r.status_code == 403
    r = await client_doc_me.post(
        "/api/v1/patients/pat-other/profile/resolve-his",
        json={"field": "allergy_history", "adopt": True},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patient_own_allowed(client_doc_me):
    """医生读自己接诊过的患者 → 200（不能误伤正常业务）。"""
    r = await client_doc_me.get("/api/v1/patients/pat-own")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_encounter_detail_cross_doctor_blocked(client_doc_me):
    """医生读他人接诊详情 → 403。"""
    r = await client_doc_me.get("/api/v1/encounters/enc-other")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_previous_record_cross_doctor_blocked(client_doc_me):
    """医生对他人接诊拉 previous-record → 403（否则可套出他人患者历史问诊）。"""
    r = await client_doc_me.get("/api/v1/encounters/enc-other/previous-record")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_quick_save_cross_doctor_blocked(client_doc_me):
    """医生在他人接诊上签发病历 → 403（篡改他人医疗文书）。"""
    r = await client_doc_me.post(
        "/api/v1/medical-records/quick-save",
        json={"encounter_id": "enc-other", "record_type": "outpatient", "content": "x"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_auto_save_draft_cross_doctor_blocked(client_doc_me):
    """医生给他人接诊自动保存草稿 → 403。"""
    r = await client_doc_me.post(
        "/api/v1/medical-records/auto-save-draft",
        json={"encounter_id": "enc-other", "record_type": "outpatient", "content": "x"},
    )
    assert r.status_code == 403


# ── 2026-08-13 第二轮审计补的三条守卫 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_create_record_cross_doctor_blocked(client_doc_me):
    """医生在他人接诊下创建病历 → 403。

    原先本端点零校验：任何登录医生都能在别人接诊下凭空建出 record，
    后续版本写入以 record_id 为起点，归属判定的源头就被污染了。
    """
    r = await client_doc_me.post(
        "/api/v1/medical-records",
        json={"encounter_id": "enc-other", "record_type": "outpatient"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_record_own_encounter_allowed(client_doc_me):
    """自己的接诊下建病历 → 201（不能误伤正常业务）。"""
    r = await client_doc_me.post(
        "/api/v1/medical-records",
        json={"encounter_id": "enc-own", "record_type": "outpatient"},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_patient_list_excludes_sensitive_phi(client_doc_me):
    """患者列表不得返回身份证/住址/紧急联系人等病案首页级 PHI。

    原先列表复用完整响应，任何登录医生翻页即可批量导出全院身份信息库；
    这些字段现在只在带归属校验 + 审计的详情端点返回。
    """
    r = await client_doc_me.get("/api/v1/patients?page=1&page_size=50")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "列表应返回患者（否则本用例失去判别力）"
    forbidden = {"id_card", "address", "ethnicity", "marital_status", "occupation",
                 "workplace", "contact_name", "contact_phone", "contact_relation",
                 "blood_type"}
    for item in items:
        leaked = forbidden & set(item)
        assert not leaked, f"患者列表泄露敏感字段：{leaked}"
    # 检索必需字段仍在（不能把功能砍废）
    assert {"id", "name"} <= set(items[0])


@pytest_asyncio.fixture
async def patched_audit_session(async_db, monkeypatch):
    """audit_service 用模块级 AsyncSessionLocal 直连真实库——patch 成复用测试
    session，让审计写入能被断言读到（与 test_admin_audit_dep 同款做法）。"""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_session_factory():
        yield async_db

    monkeypatch.setattr(
        "app.services.audit_service.AsyncSessionLocal", _fake_session_factory
    )
    yield


@pytest.mark.asyncio
async def test_profile_update_writes_audit(client_doc_me, async_db, patched_audit_session):
    """修改患者档案（过敏史等纵向 PHI）必须留审计——原先零留痕。"""
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    r = await client_doc_me.put(
        "/api/v1/patients/pat-own/profile",
        json={"allergy_history": "青霉素过敏"},
    )
    assert r.status_code == 200
    rows = (await async_db.execute(
        select(AuditLog).where(AuditLog.action == "update_patient_profile")
    )).scalars().all()
    assert rows, "档案修改未写审计日志"
    assert rows[0].resource_id == "pat-own"
    # 只记字段名不记内容（PHI 不进审计明细）
    assert "青霉素" not in (rows[0].detail or "")


@pytest.mark.asyncio
async def test_profile_concurrent_update_no_lost_field(client_doc_me, async_db):
    """并发改档案不同字段不得互相覆盖（行锁回归）。

    档案是「读整份 JSONB → Python 合并 → 整体写回」，无锁时后提交者会用自己
    读到的旧快照覆盖先提交者的修改——过敏史被静默回退是临床风险。
    单测在 SQLite 上串行执行，此处锁住的是「两次先后写入各自字段都留存」的契约
    （真并发由 with_for_update 在 PG 保证）。
    """
    r1 = await client_doc_me.put(
        "/api/v1/patients/pat-own/profile", json={"allergy_history": "青霉素过敏"}
    )
    r2 = await client_doc_me.put(
        "/api/v1/patients/pat-own/profile", json={"past_history": "高血压 10 年"}
    )
    assert r1.status_code == 200 and r2.status_code == 200
    got = (await client_doc_me.get("/api/v1/patients/pat-own/profile")).json()
    # 两个字段都在——后写的没把先写的冲掉
    assert got.get("allergy_history") == "青霉素过敏"
    assert got.get("past_history") == "高血压 10 年"


@pytest.mark.asyncio
async def test_resolve_his_pending_adopt_and_ignore(client_doc_me, async_db, patched_audit_session):
    """裁决 HIS 档案差异：采纳写入 HIS 值，忽略保留我方值；两者都清掉待处理标记。"""
    from app.models.patient import Patient

    # 用独立患者隔离：本用例直接写 ORM（绕过服务层的缓存失效），复用 pat-own
    # 会命中前面用例留在 Redis 里的档案缓存，读到旧值
    patient = Patient(id="pat-hisres", name="HIS差异患者")
    enc = Encounter(
        id="enc-hisres", patient_id="pat-hisres", doctor_id="doc-me",
        visit_type="outpatient", status="in_progress", visited_at=datetime(2026, 8, 13),
    )
    async_db.add_all([patient, enc])
    await async_db.flush()
    patient.profile = {
        "allergy_history": {"value": "青霉素过敏", "updated_at": "2026-08-01T10:00:00",
                            "his_pending": {"value": "青霉素、头孢过敏",
                                            "pushed_at": "2026-08-13T10:00:00"}},
        "past_history": {"value": "高血压", "updated_at": "2026-08-01T10:00:00",
                         "his_pending": {"value": "高血压、糖尿病",
                                         "pushed_at": "2026-08-13T10:00:00"}},
    }
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(patient, "profile")
    await async_db.commit()

    # 采纳 HIS 值
    r1 = await client_doc_me.post(
        "/api/v1/patients/pat-hisres/profile/resolve-his",
        json={"field": "allergy_history", "adopt": True},
    )
    assert r1.status_code == 200
    assert r1.json()["allergy_history"] == "青霉素、头孢过敏"
    assert not r1.json()["fields_meta"]["allergy_history"]["his_pending_value"]

    # 忽略 HIS 值（保留我方）
    r2 = await client_doc_me.post(
        "/api/v1/patients/pat-hisres/profile/resolve-his",
        json={"field": "past_history", "adopt": False},
    )
    assert r2.status_code == 200
    assert r2.json()["past_history"] == "高血压"
    assert not r2.json()["fields_meta"]["past_history"]["his_pending_value"]


@pytest.mark.asyncio
async def test_resolve_his_pending_cross_doctor_blocked(client_doc_me):
    """裁决他人患者的档案差异 → 403（与其它档案端点同一归属口径）。"""
    r = await client_doc_me.post(
        "/api/v1/patients/pat-other/profile/resolve-his",
        json={"field": "allergy_history", "adopt": True},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_radiologist_cannot_write_patient_profile(async_db):
    """影像科医生不能改患者档案（2026-08-14 第六轮审计修复）。

    读走开放读+审计（旧 assert_patient_access 已删），写必须按归属拦——
    影像科医生不能改任意患者的过敏史/既往史（临床用药依据）。
    """
    from fastapi import HTTPException

    from app.core.authz import assert_patient_write_access

    radio = User(username="radio1", password_hash="x", real_name="影像科医生",
                 role="radiologist", is_active=True)
    async_db.add(radio)
    await async_db.commit()

    # 写：必须被拦住
    with pytest.raises(HTTPException) as exc:
        await assert_patient_write_access(async_db, "pat-other", radio)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_voice_upload_requires_encounter_ownership(async_db):
    """语音上传必须校验接诊归属（2026-08-14 第七轮审计修复）。

    该端点原先**零校验**——任何登录用户（含护士/影像科）都能带上别人的
    encounter_id 往他的接诊里塞语音转写文本。而消费侧取 latest_voice_record 时
    也不比对 doctor_id，那位医生刷新工作台就会看到伪造内容写进自己的语音文本框、
    覆盖本地草稿，点「AI 整理」还会把伪造内容结构化进病历。
    """
    from fastapi import HTTPException

    from app.core.authz import assert_encounter_access

    intruder = User(username="voiceintruder", password_hash="x", real_name="闯入者",
                    role="doctor", is_active=True)
    async_db.add(intruder)
    await async_db.commit()

    # pat-other 的接诊不属于 intruder → 必须 403
    with pytest.raises(HTTPException) as exc:
        await assert_encounter_access(async_db, "enc-other", intruder)
    assert exc.value.status_code in (403, 404)


def test_voice_upload_rejects_path_traversal_ids():
    """接诊 ID 走白名单，挡住路径穿越（同轮修复）。

    encounter_id 原样拼进落盘路径，传 "../../../x" 就能把文件写到 uploads 之外。
    """
    from app.api.v1.ai_voice_records import _SAFE_ID_RE

    for bad in ["../../../../tmp/pwn", "abc/../../x", "..", "a/b", "x\y"]:
        assert not _SAFE_ID_RE.fullmatch(bad), f"路径穿越值未被拦截：{bad}"
    # 正常 UUID 必须放行
    assert _SAFE_ID_RE.fullmatch("e3b0c442-98fc-1c14-9afb-4c8996fb9242")


# ── 语音转写文本落库端点（2026-08-14 第七轮审计 #26 新增）────────────────────

@pytest.mark.asyncio
async def test_voice_transcript_save_rejects_other_doctor_encounter(client_doc_me):
    """往别人的接诊里塞转写文本 → 403。

    这是第七轮给 /voice-records/upload 补归属校验时的同一条契约：消费侧
    _encounter_snapshot 取 latest_voice_record 并不比对 doctor_id，一旦能写进去，
    那位医生下次刷新工作台就会看到伪造内容进自己的语音框、并覆盖本地草稿，
    点「AI 整理」还会把伪造内容结构化进病历。
    """
    r = await client_doc_me.post(
        "/api/v1/ai/voice-records/transcript",
        json={"encounter_id": "enc-other", "transcript": "伪造的问诊内容"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_voice_transcript_save_accepts_own_encounter(client_doc_me):
    """写自己的接诊 → 200，且真的落库（主路径原先一行都不写）。"""
    r = await client_doc_me.post(
        "/api/v1/ai/voice-records/transcript",
        json={"encounter_id": "enc-own", "transcript": "患者主诉头痛三天"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["voice_record_id"]
    assert body["has_audio"] is False
    assert body["transcript"] == "患者主诉头痛三天"


@pytest.mark.asyncio
async def test_voice_transcript_save_rejects_empty(client_doc_me):
    """空转写不建行，免得表里全是空记录。"""
    r = await client_doc_me.post(
        "/api/v1/ai/voice-records/transcript",
        json={"encounter_id": "enc-own", "transcript": "   "},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_voice_transcript_update_rejects_other_doctors_record(client_doc_me, async_db):
    """带上别人的 voice_record_id 改其转写 → 403。"""
    from app.models.voice_record import VoiceRecord

    rec = VoiceRecord(
        id="vr-other", encounter_id="enc-other", doctor_id="doc-other",
        visit_type="outpatient", raw_transcript="别人的转写", status="transcribed",
    )
    async_db.add(rec)
    await async_db.commit()

    r = await client_doc_me.post(
        "/api/v1/ai/voice-records/transcript",
        json={"encounter_id": "enc-own", "transcript": "改掉", "voice_record_id": "vr-other"},
    )
    assert r.status_code == 403


# ── quick-start 返回契约（2026-08-14 第七轮审计 #18 配套）────────────────────

@pytest.mark.asyncio
async def test_quick_start_returns_similar_patients_on_new_branch(client_doc_me):
    """新建分支必须返回 similar_patients 字段。

    这条是补课：加该字段时用脚本往两个 return 分支插入，结果同一个分支被插了
    两次、另一个一次都没有（第一次替换后的新文本里含有匹配串），ruff 的
    F601「重复键」抓到了，但当时没有任何测试覆盖返回契约。
    """
    r = await client_doc_me.post(
        "/api/v1/encounters/quick-start",
        json={"patient_name": "新患者甲", "gender": "男", "visit_type": "outpatient"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "similar_patients" in body
    assert isinstance(body["similar_patients"], list)
    assert body["resumed"] is False


@pytest.mark.asyncio
async def test_quick_start_returns_similar_patients_on_resume_branch(client_doc_me):
    """续接分支同样要返回该字段（前端两条路径读同一个 key）。"""
    payload = {"patient_name": "新患者乙", "gender": "女", "visit_type": "outpatient"}
    first = await client_doc_me.post("/api/v1/encounters/quick-start", json=payload)
    assert first.status_code == 200
    patient_id = first.json()["patient"]["id"]

    # 带 patient_id 再来一次 → 命中同一医生的进行中接诊，走续接分支
    second = await client_doc_me.post(
        "/api/v1/encounters/quick-start", json={**payload, "patient_id": patient_id}
    )
    assert second.status_code == 200
    body = second.json()
    assert body["resumed"] is True, "没走到续接分支，这条测试就没验到东西"
    assert "similar_patients" in body
