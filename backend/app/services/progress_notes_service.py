"""
病程记录业务服务（services/progress_notes_service.py）

抽出 `api/v1/progress_notes.py` 路由里的 SQL 和业务规则。
路由层职责：解析请求、鉴权、调本层函数、组装响应。
本层职责：数据访问 + 状态机 + 合法性校验（raise HTTPException）。

对外函数：
  - list_notes(db, encounter_id)
  - create_note(db, ...)
  - update_note(db, ...)          含签发冻结、status 白名单
  - delete_note(db, encounter_id, note_id)
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inpatient import ProgressNote


VALID_STATUSES = {"draft", "submitted"}


def parse_iso_naive(s: Optional[str]) -> Optional[datetime]:
    """把前端发来的 ISO 字符串解析为 naive UTC datetime（适配 TIMESTAMP WITHOUT TIME ZONE）。

    - 带 tz（'...Z' / '+08:00'）→ 转 UTC 后 strip tzinfo
    - 无 tz → 直接当本地 wall clock
    - 解析失败返回 None
    """
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def list_notes(db: AsyncSession, encounter_id: str) -> list[ProgressNote]:
    """按书写时间升序返回该接诊的全部病程记录。"""
    stmt = (
        select(ProgressNote)
        .where(ProgressNote.encounter_id == encounter_id)
        .order_by(ProgressNote.recorded_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_note(
    db: AsyncSession,
    *,
    encounter_id: str,
    note_type: str,
    title: Optional[str],
    content: str,
    recorded_at_raw: Optional[str],
    recorded_by: str,
) -> ProgressNote:
    """新建一条病程记录（默认 status=draft，recorded_at 缺省为当前时间）。"""
    parsed = parse_iso_naive(recorded_at_raw)
    recorded_at = parsed or datetime.now()

    note = ProgressNote(
        encounter_id=encounter_id,
        note_type=note_type,
        title=title,
        content=content,
        recorded_at=recorded_at,
        recorded_by=recorded_by,
        status="draft",
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def update_note(
    db: AsyncSession,
    *,
    encounter_id: str,
    note_id: str,
    title: Optional[str],
    content: Optional[str],
    status: Optional[str],
    recorded_at_raw: Optional[str],
) -> ProgressNote:
    """更新病程记录。

    规则：
      - 签发态（submitted）整条冻结：content/title/recorded_at 不可改，
        status 只能保持 submitted（不允许回退到 draft）。
      - status 白名单：只能是 draft / submitted。
    """
    note = await db.get(ProgressNote, note_id)
    if not note or note.encounter_id != encounter_id:
        raise HTTPException(status_code=404, detail="病程记录不存在")

    if note.status == "submitted":
        tried_change = any(x is not None for x in (content, title, recorded_at_raw))
        tried_status_revert = status is not None and status != "submitted"
        if tried_change or tried_status_revert:
            raise HTTPException(status_code=400, detail="已签发的病程记录不可修改")

    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status 必须是 {VALID_STATUSES} 之一",
        )

    if title is not None:
        note.title = title
    if content is not None:
        note.content = content
    if status is not None:
        note.status = status
    if recorded_at_raw is not None:
        parsed = parse_iso_naive(recorded_at_raw)
        if parsed:
            note.recorded_at = parsed

    await db.commit()
    await db.refresh(note)
    return note


async def delete_note(db: AsyncSession, encounter_id: str, note_id: str) -> None:
    """删除 draft 状态的病程记录。"""
    note = await db.get(ProgressNote, note_id)
    if not note or note.encounter_id != encounter_id:
        raise HTTPException(status_code=404, detail="病程记录不存在")
    if note.status == "submitted":
        raise HTTPException(status_code=400, detail="已签发的病程记录不可删除")
    await db.delete(note)
    await db.commit()
