"""
encounter_service.get_workspace_snapshot 测试（M5）

覆盖范围：
  - 病历版本内容三态解析（text dict / 结构化 dict / 纯字符串）
  - 跨患者权限：他人 doctor_id 访问应抛 404
  - records 排序（updated_at desc）
  - inquiry 字段 None → "" 自动归一化
  - visit_time 缺省时回退到 encounter.visited_at
  - 空快照（无 inquiry / 无 records / 无 voice）正常返回

工程注意：
  redis_cache 是模块级单例；本地常开 Redis 时 set_json 会真存到本地，
  下一个测试可能命中旧快照导致断言错乱。所有测试用 autouse fixture 把
  Redis 操作 patch 成 no-op，强制走 DB 路径。
"""
from datetime import date, datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.models.voice_record import VoiceRecord
from app.services.encounter_service import EncounterService


@pytest.fixture(autouse=True)
def disable_redis_cache(monkeypatch):
    """所有 snapshot 测试强制走 DB，避免本地 Redis 缓存污染。"""
    from app.services.redis_cache import redis_cache

    async def _miss(*_args, **_kwargs):
        return None

    async def _noop(*_args, **_kwargs):
        return True

    async def _noop_int(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(redis_cache, "get_json", _miss)
    monkeypatch.setattr(redis_cache, "set_json", _noop)
    monkeypatch.setattr(redis_cache, "delete", _noop_int)


@pytest_asyncio.fixture
async def base_encounter(async_db):
    """造一个最简洁的 patient + encounter，供后续测试派生。"""
    pat = Patient(
        id="pat-snap-1",
        name="快照测试患者",
        gender="男",
        birth_date=date(1990, 5, 1),
        profile={},  # 空档案：避免 PatientService.get_profile 报"患者不存在"
    )
    enc = Encounter(
        id="enc-snap-1",
        patient_id=pat.id,
        doctor_id="doc-snap-1",
        visit_type="outpatient",
        status="in_progress",
        is_first_visit=True,
        visited_at=datetime(2026, 4, 28, 9, 0, 0),
    )
    async_db.add_all([pat, enc])
    await async_db.commit()
    return enc


# ── 基本结构 ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_returns_expected_keys_when_empty(async_db, base_encounter):
    """无 inquiry / records / voice 时也能返回完整结构（None 占位而非 KeyError）。"""
    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    assert snap["encounter_id"] == base_encounter.id
    assert snap["visit_type"] == "outpatient"
    assert snap["status"] == "in_progress"
    assert snap["patient"] is not None
    assert snap["patient"]["name"] == "快照测试患者"
    # 空场景下三个空集合字段必须显式 None / [] / None
    assert snap["inquiry"] is None
    assert snap["records"] == []
    assert snap["active_record"] is None
    assert snap["latest_voice_record"] is None


@pytest.mark.asyncio
async def test_snapshot_unauthorized_doctor_raises_404(async_db, base_encounter):
    """跨医生越权访问应抛 404（不暴露存在性）。"""
    svc = EncounterService(async_db)
    with pytest.raises(HTTPException) as exc:
        await svc.get_workspace_snapshot(base_encounter.id, "other-doctor")
    assert exc.value.status_code == 404


# ── inquiry 序列化 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_inquiry_normalizes_none_to_empty_string(async_db, base_encounter):
    """ORM 字段为 None 时，snapshot 里应统一是 "" 而不是 None（避免前端再判空）。"""
    inq = InquiryInput(
        encounter_id=base_encounter.id,
        chief_complaint="发热",
        history_present_illness=None,  # 故意设 None
        past_history=None,
        version=1,
    )
    async_db.add(inq)
    await async_db.commit()

    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    inquiry = snap["inquiry"]
    assert inquiry is not None
    assert inquiry["chief_complaint"] == "发热"
    # 关键断言：None → ""，不是 None 本身
    assert inquiry["history_present_illness"] == ""
    assert inquiry["past_history"] == ""
    assert inquiry["temperature"] == ""  # 完全没填的字段也是 ""


@pytest.mark.asyncio
async def test_snapshot_visit_time_falls_back_to_encounter_visited_at(async_db, base_encounter):
    """inquiry.visit_time 为空时，应用 encounter.visited_at 格式化补上。"""
    inq = InquiryInput(
        encounter_id=base_encounter.id,
        chief_complaint="测试",
        visit_time=None,  # 没填，期望从 encounter 取
        version=1,
    )
    async_db.add(inq)
    await async_db.commit()

    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    # 2026-04-28 09:00:00 → "2026-04-28 09:00"
    assert snap["inquiry"]["visit_time"] == "2026-04-28 09:00"


# ── 病历内容三态解析 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_record_with_text_dict_format(async_db, base_encounter):
    """quick_save 格式 {"text": "..."} 应直接取 text 内容。"""
    record = MedicalRecord(
        id="rec-text-1",
        encounter_id=base_encounter.id,
        record_type="outpatient",
        status="submitted",
        current_version=1,
    )
    version = RecordVersion(
        medical_record_id=record.id,
        version_no=1,
        content={"text": "病历全文：发热3天，已退"},
        source="doctor_signed",
    )
    async_db.add_all([record, version])
    await async_db.commit()

    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    assert len(snap["records"]) == 1
    assert snap["records"][0]["content"] == "病历全文：发热3天，已退"
    assert snap["active_record"]["content"] == "病历全文：发热3天，已退"


@pytest.mark.asyncio
async def test_snapshot_record_with_structured_dict_format(async_db, base_encounter):
    """结构化 dict 应按字段顺序拼成可读段落（带【主诉】等标签）。"""
    record = MedicalRecord(
        id="rec-struct-1",
        encounter_id=base_encounter.id,
        record_type="outpatient",
        status="draft",
        current_version=1,
    )
    version = RecordVersion(
        medical_record_id=record.id,
        version_no=1,
        content={
            "chief_complaint": "发热3天",
            "history_present_illness": "高热伴乏力",
            "treatment_plan": "对症退热",
        },
        source="ai_generate",
    )
    async_db.add_all([record, version])
    await async_db.commit()

    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    content = snap["records"][0]["content"]
    assert "【主诉】" in content and "发热3天" in content
    assert "【现病史】" in content and "高热伴乏力" in content
    assert "【诊疗计划】" in content and "对症退热" in content
    # 主诉应排在现病史之前（按 _RECORD_CONTENT_LABELS 顺序）
    assert content.index("【主诉】") < content.index("【现病史】")


@pytest.mark.asyncio
async def test_snapshot_record_with_plain_string_content(async_db, base_encounter):
    """纯字符串内容应原样返回（兼容历史数据）。"""
    record = MedicalRecord(
        id="rec-str-1",
        encounter_id=base_encounter.id,
        record_type="outpatient",
        status="draft",
        current_version=1,
    )
    # JSONB 在 SQLite 测试环境下被替换成 JSON，可以直接存字符串
    version = RecordVersion(
        medical_record_id=record.id,
        version_no=1,
        content="历史纯文本病历内容",
        source="manual",
    )
    async_db.add_all([record, version])
    await async_db.commit()

    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    assert snap["records"][0]["content"] == "历史纯文本病历内容"


# ── records 排序 + 多条 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_records_ordered_by_updated_at_desc(async_db, base_encounter):
    """多份病历按 updated_at 倒序，第一条是 active_record。"""
    older = MedicalRecord(
        id="rec-older",
        encounter_id=base_encounter.id,
        record_type="outpatient",
        status="draft",
        current_version=1,
        updated_at=datetime(2026, 4, 27, 8, 0, 0),
    )
    newer = MedicalRecord(
        id="rec-newer",
        encounter_id=base_encounter.id,
        record_type="outpatient",
        status="draft",
        current_version=1,
        updated_at=datetime(2026, 4, 28, 10, 0, 0),
    )
    async_db.add_all([
        older, newer,
        RecordVersion(medical_record_id=older.id, version_no=1, content={"text": "旧"}, source="manual"),
        RecordVersion(medical_record_id=newer.id, version_no=1, content={"text": "新"}, source="manual"),
    ])
    await async_db.commit()

    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    assert len(snap["records"]) == 2
    assert snap["records"][0]["record_id"] == "rec-newer"
    assert snap["records"][1]["record_id"] == "rec-older"
    assert snap["active_record"]["record_id"] == "rec-newer"


@pytest.mark.asyncio
async def test_snapshot_record_without_version_returns_empty_content(async_db, base_encounter):
    """病历 current_version 指向不存在的 version_no 时不应炸，content 应为空字符串。"""
    record = MedicalRecord(
        id="rec-noversion",
        encounter_id=base_encounter.id,
        record_type="outpatient",
        status="draft",
        current_version=5,  # 故意指向不存在的版本号
    )
    async_db.add(record)
    await async_db.commit()

    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    assert len(snap["records"]) == 1
    assert snap["records"][0]["content"] == ""


# ── voice 记录 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_includes_latest_voice_record(async_db, base_encounter):
    """voice 记录应取最新一条（按 updated_at + created_at 倒序）。"""
    voice = VoiceRecord(
        encounter_id=base_encounter.id,
        doctor_id="doc-snap-1",
        status="structured",
        raw_transcript="医生说话内容",
        transcript_summary="发热咨询",
    )
    async_db.add(voice)
    await async_db.commit()

    svc = EncounterService(async_db)
    snap = await svc.get_workspace_snapshot(base_encounter.id, "doc-snap-1")

    assert snap["latest_voice_record"] is not None
    assert snap["latest_voice_record"]["raw_transcript"] == "医生说话内容"
    assert snap["latest_voice_record"]["transcript_summary"] == "发热咨询"
    assert snap["latest_voice_record"]["speaker_dialogue"] == []  # 未填 → 空列表
