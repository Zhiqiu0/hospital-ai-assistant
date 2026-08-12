"""AI 采纳度量（编辑距离数据管道）测试——2026-08-12 反馈闭环。

覆盖范围：
  - text_similarity：相同/为空/部分修改 的相似度语义
  - quick_save 签发钩子：有 AI 草稿 → 签发版本落 ai_similarity + ai_base_version_no；
    纯手写（无 AI 版本）→ 两列为 NULL；多版 AI 取最近一版为基准
  - 非致命性：相似度计算抛异常不阻断签发（签发是命门主路径）
  - adoption_stats：看板聚合口径（total/avg/high/low）
"""
from datetime import datetime

import pytest

from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.services._ai_adoption import adoption_stats, text_similarity
from app.services.medical_record_service import MedicalRecordService


@pytest.fixture(autouse=True)
def disable_cache_invalidation(monkeypatch):
    """避免测试依赖本地 Redis：缓存失效调用全部 no-op。"""
    from app.services import encounter_service

    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(encounter_service, "invalidate_encounter_snapshot", _noop)
    monkeypatch.setattr(encounter_service, "invalidate_my_encounters", _noop)


async def _make_encounter(async_db, *, encounter_id: str) -> Encounter:
    """构造一条 in_progress 门诊接诊（含必需的 patient FK）。"""
    pat_id = f"pat-{encounter_id}"
    async_db.add_all([
        Patient(id=pat_id, name=f"患者-{encounter_id}"),
        Encounter(
            id=encounter_id, patient_id=pat_id, doctor_id="doc-adopt-1",
            visit_type="outpatient", status="in_progress", is_first_visit=True,
            visited_at=datetime(2026, 8, 12, 9, 0, 0),
        ),
    ])
    await async_db.commit()
    return await async_db.get(Encounter, encounter_id)


async def _add_ai_version(async_db, record: MedicalRecord, *, version_no: int,
                          text: str, source: str = "ai_generate") -> None:
    """给病历补一版 AI 草稿（模拟 AI 生成落库）。"""
    async_db.add(RecordVersion(
        medical_record_id=record.id, version_no=version_no,
        content={"text": text}, source=source,
    ))
    record.current_version = version_no
    await async_db.commit()


async def _make_draft_record(async_db, encounter_id: str) -> MedicalRecord:
    """构造一份 draft 病历主表记录。"""
    rec = MedicalRecord(
        id=f"rec-{encounter_id}", encounter_id=encounter_id,
        record_type="outpatient", status="draft", current_version=0,
    )
    async_db.add(rec)
    await async_db.commit()
    return rec


async def _signed_version(async_db, record: MedicalRecord) -> RecordVersion:
    """取签发版本行。"""
    from sqlalchemy import select
    return (await async_db.execute(
        select(RecordVersion).where(
            RecordVersion.medical_record_id == record.id,
            RecordVersion.source == "doctor_signed",
        )
    )).scalar_one()


# ── text_similarity 语义 ─────────────────────────────────────────────────────


def test_similarity_identical_is_one():
    """原样采纳 → 1.0。"""
    assert text_similarity("主诉：发热3天。", "主诉：发热3天。") == 1.0


def test_similarity_empty_is_zero():
    """任一侧为空 → 0（无可比性，不算采纳）。"""
    assert text_similarity("", "正文") == 0.0
    assert text_similarity("正文", "") == 0.0


def test_similarity_partial_edit_between_zero_and_one():
    """小幅修改 → 明显高于0低于1。"""
    s = text_similarity("主诉：发热3天，咳嗽2天。", "主诉：发热3天，咳嗽伴咽痛2天。")
    assert 0.5 < s < 1.0


# ── 签发钩子 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sign_with_ai_draft_records_similarity(async_db):
    """签发前有 AI 草稿：签发版本应落相似度与基准版本号。"""
    enc = await _make_encounter(async_db, encounter_id="enc-adopt-1")
    rec = await _make_draft_record(async_db, enc.id)
    await _add_ai_version(async_db, rec, version_no=1, text="AI草稿：发热3天，咳嗽。")

    svc = MedicalRecordService(async_db)
    record = await svc.quick_save(
        encounter_id=enc.id, record_type="outpatient",
        content="AI草稿：发热3天，咳嗽。", doctor_id="doc-adopt-1",
    )

    ver = await _signed_version(async_db, record)
    assert ver.ai_similarity == 1.0          # 原样采纳
    assert ver.ai_base_version_no == 1


@pytest.mark.asyncio
async def test_sign_without_ai_draft_leaves_null(async_db):
    """纯手写签发（无 AI 版本）：两列保持 NULL，看板聚合天然排除。"""
    enc = await _make_encounter(async_db, encounter_id="enc-adopt-2")

    svc = MedicalRecordService(async_db)
    record = await svc.quick_save(
        encounter_id=enc.id, record_type="outpatient",
        content="手写病历正文", doctor_id="doc-adopt-1",
    )

    ver = await _signed_version(async_db, record)
    assert ver.ai_similarity is None
    assert ver.ai_base_version_no is None


@pytest.mark.asyncio
async def test_sign_uses_latest_ai_version_as_base(async_db):
    """多版 AI 草稿：以最近一版（版本号最大）为对比基准。"""
    enc = await _make_encounter(async_db, encounter_id="enc-adopt-3")
    rec = await _make_draft_record(async_db, enc.id)
    await _add_ai_version(async_db, rec, version_no=1, text="第一版草稿")
    await _add_ai_version(async_db, rec, version_no=2, text="润色后的第二版草稿",
                          source="ai_polish")

    svc = MedicalRecordService(async_db)
    record = await svc.quick_save(
        encounter_id=enc.id, record_type="outpatient",
        content="润色后的第二版草稿", doctor_id="doc-adopt-1",
    )

    ver = await _signed_version(async_db, record)
    assert ver.ai_base_version_no == 2
    assert ver.ai_similarity == 1.0


@pytest.mark.asyncio
async def test_similarity_failure_does_not_block_sign(async_db, monkeypatch):
    """相似度计算抛异常：签发必须照常成功（指标是旁路，签发是主路径）。"""
    from app.services import _ai_adoption

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("metric exploded")

    monkeypatch.setattr(_ai_adoption, "latest_ai_version", _boom)
    enc = await _make_encounter(async_db, encounter_id="enc-adopt-4")

    svc = MedicalRecordService(async_db)
    record = await svc.quick_save(
        encounter_id=enc.id, record_type="outpatient",
        content="正常签发", doctor_id="doc-adopt-1",
    )
    assert record.status == "submitted"


# ── 端到端回归（2026-08-12 复检修复）：auto-save 不得摧毁 AI 对比基线 ────────


@pytest.mark.asyncio
async def test_autosave_preserves_ai_original_for_similarity(async_db):
    """真实工作流：AI 生成 → 医生编辑器大改（auto-save 高频覆写）→ 签发。

    修复前 auto-save 原地覆写 ai_generated 版本，签发时的对比基线是医生
    5 秒前自己的文本，ai_similarity 恒≈1（指标系统性虚高）。
    修复后 AI 原文冻结为不可变版本，相似度反映医生真实修改量。
    """
    enc = await _make_encounter(async_db, encounter_id="enc-adopt-e2e")
    svc = MedicalRecordService(async_db)

    ai_text = "主诉：发热3天。现病史：3天前受凉后发热，最高38.5℃，伴咳嗽咳痰。"
    await svc.save_ai_draft(
        encounter_id=enc.id, record_type="outpatient",
        content=ai_text, user_id="doc-adopt-1",
    )
    # 医生在编辑器里大改，auto-save 触发多次
    doctor_text = "主诉：腹痛2小时。现病史：2小时前进食后突发上腹绞痛，无发热。"
    for _ in range(2):
        await svc.auto_save_draft(
            encounter_id=enc.id, record_type="outpatient",
            content=doctor_text, user_id="doc-adopt-1",
        )
    record = await svc.quick_save(
        encounter_id=enc.id, record_type="outpatient",
        content=doctor_text, doctor_id="doc-adopt-1",
    )

    # AI 原文版本未被覆写（v1 仍是 AI 原文）
    from sqlalchemy import select
    v1 = (await async_db.execute(
        select(RecordVersion).where(
            RecordVersion.medical_record_id == record.id,
            RecordVersion.version_no == 1,
        )
    )).scalar_one()
    assert v1.source == "ai_generated"
    assert v1.content == {"text": ai_text}

    # 签发版本的对比基线是 AI 原文：大改后相似度必须明显低于 1
    ver = await _signed_version(async_db, record)
    assert ver.ai_base_version_no == 1
    assert ver.ai_similarity is not None and ver.ai_similarity < 0.8


@pytest.mark.asyncio
async def test_pure_manual_autosave_not_counted_as_ai(async_db):
    """纯手写工作流：没有 AI 生成、只有 auto-save → 签发不计入 AI 采纳统计。

    修复前 auto-save 首版统一标 'ai_generated'，纯手写病历会被误算成
    "AI 草稿被原样采纳"（相似度≈1），污染看板。
    """
    enc = await _make_encounter(async_db, encounter_id="enc-adopt-manual")
    svc = MedicalRecordService(async_db)

    await svc.auto_save_draft(
        encounter_id=enc.id, record_type="outpatient",
        content="纯手写病历正文", user_id="doc-adopt-1",
    )
    record = await svc.quick_save(
        encounter_id=enc.id, record_type="outpatient",
        content="纯手写病历正文", doctor_id="doc-adopt-1",
    )

    ver = await _signed_version(async_db, record)
    assert ver.ai_similarity is None
    assert ver.ai_base_version_no is None


# ── 看板聚合 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_adoption_stats_aggregates_signed_versions(async_db):
    """聚合口径：只算 doctor_signed 且有相似度的版本；分 high(≥0.8)/low(<0.5)。"""
    rec = await _make_draft_record(
        async_db, (await _make_encounter(async_db, encounter_id="enc-adopt-5")).id
    )
    for no, sim in [(1, 0.95), (2, 0.6), (3, 0.3)]:
        async_db.add(RecordVersion(
            medical_record_id=rec.id, version_no=no, content={"text": "x"},
            source="doctor_signed", ai_similarity=sim, ai_base_version_no=no,
        ))
    # 干扰项：AI 草稿版本不应计入
    async_db.add(RecordVersion(
        medical_record_id=rec.id, version_no=4, content={"text": "x"},
        source="ai_generate",
    ))
    await async_db.commit()

    stats = await adoption_stats(async_db, datetime(2026, 1, 1))
    assert stats["total"] == 3
    assert stats["avg_similarity"] == round((0.95 + 0.6 + 0.3) / 3, 3)
    assert stats["high_adoption"] == 1
    assert stats["low_adoption"] == 1
