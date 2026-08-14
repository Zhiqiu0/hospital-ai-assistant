"""回写 payload 必须带 record_no（2026-08-14 第八轮审计，两个审计员独立发现）。

接口规范 §2.5：「回写以（visit_id + record_type + record_no）为幂等键——
该键对应的文书在 HIS 尚无则新建，已有则覆盖更新」「住院一次就诊有多份文书……
靠 record_no 区分，避免互相覆盖或重复」。

第六轮的 i20260814recordno 迁移专门为此在我方库里加了 record_no 并让签发时
正确递增，**但回写 payload 从头到尾没带上它**：住院 15 份日常病程每次回写的
(visit_id, record_type) 逐字相同，HIS 按规范只能认定是同一份文书被覆盖 14 次。
我方库里 15 份都在，HIS 病案里只剩最后一份——而**法定病案是 HIS 那一份**。
"""

from datetime import date, datetime

import pytest

from app.his_adapter.writeback_builder import build_writeback_payload
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient


async def _seed_encounter(db, visit_type="inpatient") -> str:
    db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-1",
        visit_type=visit_type, status="in_progress",
        visited_at=datetime(2026, 8, 1),
        visit_no="ZY20260801",
        his_external_ref={"source": "admit_push", "his_visit_no": "ZY20260801",
                          "hospital_code": "H1", "doctor_code": "D1001"},
    ))
    await db.flush()
    return "enc-1"


async def _sign_record(db, *, record_type: str, record_no: int, text: str) -> None:
    """造一份已签发的病历（含当前版本正文）。"""
    rec = MedicalRecord(
        id=f"rec-{record_type}-{record_no}", encounter_id="enc-1",
        record_type=record_type, record_no=record_no,
        status="submitted", current_version=1,
        submitted_at=datetime(2026, 8, record_no, 10, 0),
        updated_at=datetime(2026, 8, record_no, 10, 0),
    )
    db.add(rec)
    await db.flush()
    db.add(RecordVersion(
        id=f"ver-{record_type}-{record_no}", medical_record_id=rec.id,
        version_no=1, content={"text": text},
        source="doctor_signed", triggered_by="doc-1",
    ))
    await db.flush()


@pytest.mark.asyncio
async def test_住院多份病程回写各带自己的record_no(async_db):
    """核心断言：三份病程的幂等键必须互不相同。"""
    await _seed_encounter(async_db)

    seen = []
    for no in (1, 2, 3):
        await _sign_record(
            async_db, record_type="course_record", record_no=no,
            text=f"8月{no}日病程正文",
        )
        payload = await build_writeback_payload(async_db, "enc-1")
        seen.append((payload["visit_id"], payload["record_type"], payload.get("record_no")))

    assert seen[0][2] == 1 and seen[1][2] == 2 and seen[2][2] == 3, f"record_no 未下发：{seen}"
    assert len(set(seen)) == 3, f"三份病程的幂等键重复了，HIS 侧会互相覆盖：{seen}"


@pytest.mark.asyncio
async def test_payload包含record_no字段(async_db):
    """防回退：字段本身必须存在于 payload 的键里。"""
    await _seed_encounter(async_db)
    await _sign_record(async_db, record_type="admission_note", record_no=1, text="入院记录")

    payload = await build_writeback_payload(async_db, "enc-1")
    assert "record_no" in payload, "payload 里没有 record_no 这个键"
    assert payload["record_no"] == 1


@pytest.mark.asyncio
async def test_门诊单份文书record_no不影响原有行为(async_db):
    """门急诊一次接诊一份病历，规范允许 record_no 可空。"""
    await _seed_encounter(async_db, visit_type="outpatient")
    await _sign_record(async_db, record_type="outpatient", record_no=1, text="门诊病历")

    payload = await build_writeback_payload(async_db, "enc-1")
    assert payload["record_type"] == "outpatient"
    # 有值就带上（我方库里 record_no 默认回填为 1），不为 None 也不报错
    assert payload["record_no"] in (1, None)


# ── HTTP 回写幂等键（第八轮审计）────────────────────────────────────────────

def test_http重试链路共用同一个幂等键():
    """整条 HTTP 回写原先没有任何幂等键：HIS 处理慢导致 30s 读超时时，
    HIS 其实已落库，我方判失败立刻原样重发 → 病案里多一份；
    对账任务还会最多再重投 5 次，每次全新 nonce，HIS 无从判重。
    """
    import asyncio
    import httpx

    from app.his_adapter import writeback_sender as ws

    seen_ids: list[str] = []
    seen_nonces: list[str] = []

    class _FakeClient:
        async def post(self, url, content=None, headers=None):
            seen_ids.append(headers["X-Request-Id"])
            seen_nonces.append(headers["X-Nonce"])
            # 前两次 500 触发重试，第三次成功
            code = 500 if len(seen_ids) < 3 else 200
            return httpx.Response(code, request=httpx.Request("POST", "http://x"))

    # 退避基数压到 0，避免测试真的等 1+2 秒
    original = ws._RETRY_BACKOFF_BASE
    ws._RETRY_BACKOFF_BASE = 0
    try:
        asyncio.run(ws._post_with_retry(
            _FakeClient(), "http://x", "{}", 2, request_id="wb-V001-course_record-3",
        ))
    finally:
        ws._RETRY_BACKOFF_BASE = original

    assert len(seen_ids) == 3
    assert set(seen_ids) == {"wb-V001-course_record-3"}, "重试时幂等键变了，HIS 无法判重"
    # nonce 必须每次都换（防重放要求），与幂等键是两回事
    assert len(set(seen_nonces)) == 3, "nonce 没有每次重新生成"
