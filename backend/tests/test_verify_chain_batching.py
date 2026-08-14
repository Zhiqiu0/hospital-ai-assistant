"""verify_chain 分批与批量取病历的回归测试（2026-08-14 第七轮审计 #12）。

原实现把**所有**签发版本一次 .all() 灌进内存（正文+患者快照，几万份就能让
4GB 生产机 OOM），并且逐行 db.get(MedicalRecord) 形成 N+1。

改成分批之后最容易踩的坑是：**链接校验跨批失效**——第 2 批里的版本引用的是
第 1 批里的哈希，如果 known_hashes 也跟着分批构造就会误报"链断裂"。
本测试把批大小压到 2，强制走多批路径，锁死这一点。
"""

import pytest

from app.models.medical_record import MedicalRecord, RecordVersion
from app.services import _record_signature as sig


async def _make_chain(db, n: int) -> None:
    """造一条 n 环的合法签名链（每环引用上一环的 sign_hash）。"""
    prev = sig.GENESIS_HASH
    for i in range(n):
        record = MedicalRecord(
            id=f"rec-{i}",
            encounter_id=f"enc-{i}",
            record_type="outpatient",
            status="submitted",
            patient_snapshot={"name": f"患者{i}"},
        )
        db.add(record)
        await db.flush()

        content = {"text": f"第 {i} 份病历正文"}
        version = RecordVersion(
            id=f"ver-{i}",
            medical_record_id=record.id,
            version_no=1,
            content=content,
            source="doctor_signed",
            triggered_by=f"doctor-{i}",
            prev_hash=prev,
        )
        version.sign_hash = sig.compute_sign_hash(
            content_text=sig.content_text_of(content),
            patient_snapshot=record.patient_snapshot,
            doctor_id=version.triggered_by,
            submitted_at_iso="",
            prev_hash=prev,
        )
        db.add(version)
        await db.flush()
        prev = version.sign_hash


@pytest.mark.asyncio
async def test_完好的链跨多批仍判定通过(async_db, monkeypatch):
    """批大小压到 2、造 7 环，强制走 4 批。"""
    monkeypatch.setattr(sig, "_VERIFY_CHUNK", 2)
    await _make_chain(async_db, 7)

    issues = await sig.verify_chain(async_db)
    assert issues == [], f"完好的链被误报：{issues}"


@pytest.mark.asyncio
async def test_删掉中间一环仍能被检出(async_db, monkeypatch):
    """核心保护：删除链中任一环，后继的 prev_hash 悬空必须报出来。"""
    monkeypatch.setattr(sig, "_VERIFY_CHUNK", 2)
    await _make_chain(async_db, 7)

    victim = await async_db.get(RecordVersion, "ver-3")
    await async_db.delete(victim)
    await async_db.flush()

    issues = await sig.verify_chain(async_db)
    assert any("链断裂" in i["issue"] for i in issues), "删掉中间一环没被检出"


@pytest.mark.asyncio
async def test_改正文但不重算哈希会被检出(async_db, monkeypatch):
    monkeypatch.setattr(sig, "_VERIFY_CHUNK", 2)
    await _make_chain(async_db, 5)

    tampered = await async_db.get(RecordVersion, "ver-2")
    tampered.content = {"text": "被偷偷改过的正文"}
    await async_db.flush()

    issues = await sig.verify_chain(async_db)
    assert any("内容被篡改" in i["issue"] for i in issues), "改正文没被检出"


@pytest.mark.asyncio
async def test_改患者快照会被检出(async_db, monkeypatch):
    """病历是跟着 medical_records 走的——批量取病历后不能漏掉快照这一路输入。"""
    monkeypatch.setattr(sig, "_VERIFY_CHUNK", 2)
    await _make_chain(async_db, 5)

    record = await async_db.get(MedicalRecord, "rec-1")
    record.patient_snapshot = {"name": "换成了另一个人"}
    await async_db.flush()

    issues = await sig.verify_chain(async_db)
    assert any("内容被篡改" in i["issue"] for i in issues), "改患者快照没被检出"


@pytest.mark.asyncio
async def test_空库返回空清单(async_db):
    assert await sig.verify_chain(async_db) == []
