"""
病程记录服务单元测试（app/services/progress_notes_service.py）

覆盖范围：
  - parse_iso_naive 时区处理：Z 后缀 / +08:00 偏移 / 无时区 / 非法字符串 / 空值
  - list_notes：按 recorded_at 升序返回、按 encounter_id 隔离
  - create_note：默认 status=draft、recorded_at 缺省取当前时间、带时区入参转 UTC naive
  - update_note：草稿可改字段、status 白名单（draft/submitted）、404 分支
  - 签发冻结：submitted 后 content/title/recorded_at 不可改、status 不可回退 draft
  - delete_note：draft 可删、submitted 不可删、404 分支

说明：ProgressNote.encounter_id 无外键约束，测试直接用字符串 ID，
不需要真实建 Encounter（service 层也不校验 encounter 存在性——由路由层鉴权负责）。
"""
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.inpatient import ProgressNote
from app.services import progress_notes_service as pn


# ── parse_iso_naive：时区处理（纯函数，无需 DB）────────────────────────────────


def test_parse_iso_z_suffix_converts_to_utc_naive():
    """'Z' 后缀（UTC 时间）应解析为 naive UTC datetime，tzinfo 被剥离。"""
    dt = pn.parse_iso_naive("2026-06-01T08:00:00Z")
    assert dt == datetime(2026, 6, 1, 8, 0, 0)
    assert dt.tzinfo is None


def test_parse_iso_offset_converts_to_utc():
    """带 +08:00 偏移的时间应换算到 UTC（16:00+08:00 → 08:00 naive）。"""
    dt = pn.parse_iso_naive("2026-06-01T16:00:00+08:00")
    assert dt == datetime(2026, 6, 1, 8, 0, 0)
    assert dt.tzinfo is None


def test_parse_iso_naive_passthrough():
    """无时区的字符串当本地 wall clock 原样解析，不做任何换算。"""
    dt = pn.parse_iso_naive("2026-06-01T09:30:15")
    assert dt == datetime(2026, 6, 1, 9, 30, 15)
    assert dt.tzinfo is None


def test_parse_iso_invalid_returns_none():
    """非法字符串解析失败返回 None（不抛异常，由调用方兜底）。"""
    assert pn.parse_iso_naive("not-a-date") is None


def test_parse_iso_empty_returns_none():
    """None / 空串都返回 None。"""
    assert pn.parse_iso_naive(None) is None
    assert pn.parse_iso_naive("") is None


# ── 测试辅助：用 service 真实路径创建病程记录 ─────────────────────────────────


async def _mk_note(db, *, encounter_id="enc-pn-1", note_type="daily_course",
                   title=None, content="病程正文", recorded_at_raw=None,
                   recorded_by="测试医生"):
    """通过 create_note 走真实创建路径，返回 ORM 对象。"""
    return await pn.create_note(
        db,
        encounter_id=encounter_id,
        note_type=note_type,
        title=title,
        content=content,
        recorded_at_raw=recorded_at_raw,
        recorded_by=recorded_by,
    )


# ── create_note ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_note_defaults(async_db):
    """新建记录默认 status=draft；recorded_at 缺省时自动取当前时间。"""
    before = datetime.now()
    note = await _mk_note(async_db, note_type="first_course", title="首次病程")
    after = datetime.now()
    assert note.status == "draft"
    assert note.note_type == "first_course"
    assert note.title == "首次病程"
    assert note.recorded_by == "测试医生"
    # recorded_at 落在创建前后区间内（缺省取 datetime.now()）
    assert before <= note.recorded_at <= after


@pytest.mark.asyncio
async def test_create_note_with_tz_recorded_at(async_db):
    """带 +08:00 时区的 recorded_at 入库前换算为 UTC naive 存储。"""
    note = await _mk_note(async_db, recorded_at_raw="2026-06-01T16:00:00+08:00")
    assert note.recorded_at == datetime(2026, 6, 1, 8, 0, 0)


@pytest.mark.asyncio
async def test_create_note_invalid_recorded_at_falls_back_to_now(async_db):
    """recorded_at 字符串非法时不报错，回退为当前时间。"""
    before = datetime.now()
    note = await _mk_note(async_db, recorded_at_raw="garbage-time")
    assert note.recorded_at >= before


# ── list_notes ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_notes_sorted_and_isolated(async_db):
    """列表按 recorded_at 升序；不同 encounter 的记录互不可见。"""
    # 故意先建"晚"的再建"早"的，验证排序不是按插入顺序
    await _mk_note(async_db, encounter_id="enc-A", content="第二条",
                   recorded_at_raw="2026-06-02T10:00:00")
    await _mk_note(async_db, encounter_id="enc-A", content="第一条",
                   recorded_at_raw="2026-06-01T10:00:00")
    await _mk_note(async_db, encounter_id="enc-B", content="别的接诊")

    notes = await pn.list_notes(async_db, "enc-A")
    assert len(notes) == 2
    assert [n.content for n in notes] == ["第一条", "第二条"]


@pytest.mark.asyncio
async def test_list_notes_empty_encounter(async_db):
    """无记录的接诊返回空列表（不是 None）。"""
    assert await pn.list_notes(async_db, "enc-nothing") == []


# ── update_note：草稿主路径 + 404 + status 白名单 ─────────────────────────────


@pytest.mark.asyncio
async def test_update_draft_fields(async_db):
    """草稿状态下 title/content/recorded_at 都可改。"""
    note = await _mk_note(async_db)
    updated = await pn.update_note(
        async_db,
        encounter_id=note.encounter_id,
        note_id=note.id,
        title="新标题",
        content="新正文",
        status=None,
        recorded_at_raw="2026-06-03T00:00:00Z",
    )
    assert updated.title == "新标题"
    assert updated.content == "新正文"
    assert updated.recorded_at == datetime(2026, 6, 3, 0, 0, 0)
    assert updated.status == "draft"  # 未传 status 保持草稿


@pytest.mark.asyncio
async def test_update_submit_transition(async_db):
    """draft → submitted 是合法状态流转（签发）。"""
    note = await _mk_note(async_db)
    updated = await pn.update_note(
        async_db, encounter_id=note.encounter_id, note_id=note.id,
        title=None, content=None, status="submitted", recorded_at_raw=None,
    )
    assert updated.status == "submitted"


@pytest.mark.asyncio
async def test_update_invalid_status_rejected(async_db):
    """status 白名单：非 draft/submitted 的值一律 400。"""
    note = await _mk_note(async_db)
    with pytest.raises(HTTPException) as exc:
        await pn.update_note(
            async_db, encounter_id=note.encounter_id, note_id=note.id,
            title=None, content=None, status="archived", recorded_at_raw=None,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_update_unknown_note_404(async_db):
    """note_id 不存在 → 404。"""
    with pytest.raises(HTTPException) as exc:
        await pn.update_note(
            async_db, encounter_id="enc-pn-1", note_id="no-such-id",
            title="x", content=None, status=None, recorded_at_raw=None,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_wrong_encounter_404(async_db):
    """note 存在但 encounter_id 不匹配 → 404（防越权访问别的接诊）。"""
    note = await _mk_note(async_db, encounter_id="enc-owner")
    with pytest.raises(HTTPException) as exc:
        await pn.update_note(
            async_db, encounter_id="enc-other", note_id=note.id,
            title="x", content=None, status=None, recorded_at_raw=None,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_invalid_recorded_at_ignored(async_db):
    """草稿下 recorded_at 传非法字符串：解析失败时保持原值不变（不报错）。"""
    note = await _mk_note(async_db, recorded_at_raw="2026-06-01T08:00:00")
    original = note.recorded_at
    updated = await pn.update_note(
        async_db, encounter_id=note.encounter_id, note_id=note.id,
        title=None, content=None, status=None, recorded_at_raw="bad-value",
    )
    assert updated.recorded_at == original


# ── 签发冻结：submitted 后不可改不可删 ────────────────────────────────────────


async def _mk_submitted(db, **kwargs):
    """创建并签发一条病程记录（走 update_note 真实签发路径）。"""
    note = await _mk_note(db, **kwargs)
    return await pn.update_note(
        db, encounter_id=note.encounter_id, note_id=note.id,
        title=None, content=None, status="submitted", recorded_at_raw=None,
    )


@pytest.mark.asyncio
async def test_submitted_content_frozen(async_db):
    """签发后改 content → 400。"""
    note = await _mk_submitted(async_db)
    with pytest.raises(HTTPException) as exc:
        await pn.update_note(
            async_db, encounter_id=note.encounter_id, note_id=note.id,
            title=None, content="篡改正文", status=None, recorded_at_raw=None,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_submitted_title_and_time_frozen(async_db):
    """签发后改 title / recorded_at 同样 400。"""
    note = await _mk_submitted(async_db)
    for kwargs in (
        {"title": "新标题", "content": None, "recorded_at_raw": None},
        {"title": None, "content": None, "recorded_at_raw": "2026-06-05T00:00:00Z"},
    ):
        with pytest.raises(HTTPException) as exc:
            await pn.update_note(
                async_db, encounter_id=note.encounter_id, note_id=note.id,
                status=None, **kwargs,
            )
        assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_submitted_status_cannot_revert(async_db):
    """签发后 status 不允许回退 draft → 400。"""
    note = await _mk_submitted(async_db)
    with pytest.raises(HTTPException) as exc:
        await pn.update_note(
            async_db, encounter_id=note.encounter_id, note_id=note.id,
            title=None, content=None, status="draft", recorded_at_raw=None,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_submitted_keep_submitted_is_noop_ok(async_db):
    """签发后重复提交 status=submitted（幂等操作）不报错。"""
    note = await _mk_submitted(async_db)
    updated = await pn.update_note(
        async_db, encounter_id=note.encounter_id, note_id=note.id,
        title=None, content=None, status="submitted", recorded_at_raw=None,
    )
    assert updated.status == "submitted"


# ── delete_note ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_draft_ok(async_db):
    """草稿可删除，删除后查不到。"""
    note = await _mk_note(async_db)
    await pn.delete_note(async_db, note.encounter_id, note.id)
    remaining = (await async_db.execute(
        select(ProgressNote).where(ProgressNote.id == note.id)
    )).scalar_one_or_none()
    assert remaining is None


@pytest.mark.asyncio
async def test_delete_submitted_rejected(async_db):
    """已签发的记录不可删除 → 400（病历是法律文件，签发即冻结）。"""
    note = await _mk_submitted(async_db)
    with pytest.raises(HTTPException) as exc:
        await pn.delete_note(async_db, note.encounter_id, note.id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_unknown_404(async_db):
    """删除不存在的记录 / encounter 不匹配 → 404。"""
    with pytest.raises(HTTPException) as exc:
        await pn.delete_note(async_db, "enc-x", "no-such-note")
    assert exc.value.status_code == 404

    note = await _mk_note(async_db, encounter_id="enc-owner-2")
    with pytest.raises(HTTPException) as exc:
        await pn.delete_note(async_db, "enc-stranger", note.id)
    assert exc.value.status_code == 404


class TestNoteTypeWhitelist:
    """note_type 白名单校验（2026-06-11 补——之前任意字符串可入库）。"""

    async def test_非法类型_400(self, async_db):
        from fastapi import HTTPException
        import pytest as _pytest
        from app.services import progress_notes_service as svc

        with _pytest.raises(HTTPException) as exc_info:
            await svc.create_note(
                async_db,
                encounter_id="enc-x",
                note_type="not_a_real_type",
                title=None,
                content="内容",
                recorded_at_raw=None,
                recorded_by="doc-1",
            )
        assert exc_info.value.status_code == 400

    async def test_合法类型_全部可创建(self, async_db):
        from app.services import progress_notes_service as svc

        for nt in sorted(svc.VALID_NOTE_TYPES):
            note = await svc.create_note(
                async_db,
                encounter_id="enc-whitelist",
                note_type=nt,
                title=None,
                content=f"{nt} 内容",
                recorded_at_raw=None,
                recorded_by="doc-1",
            )
            assert note.note_type == nt
