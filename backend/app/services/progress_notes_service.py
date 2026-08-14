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

from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter
from app.models.inpatient import ProgressNote


VALID_STATUSES = {"draft", "submitted"}

# 病程记录类型白名单（2026-06-11 补，与前端 domain/inpatient/recordRules.ts 的
# NOTE_TYPE_RULES 键一致）。此前 note_type 无校验，任意字符串可入库——
# 脏类型会让前端时间轴按未知类型渲染兜底样式且无法套用时限规则
VALID_NOTE_TYPES = {"first_course", "daily_course", "surgery_pre", "surgery_post", "discharge"}


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
        # 带时区的输入换算到服务器本地时间后剥离 tzinfo（2026-08-11 时区统一：
        # 全项目 naive 时间=服务器本地时间，生产 TZ=Asia/Shanghai，原先换算到
        # UTC 会与其余落库时间差 8 小时）
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


async def list_notes(db: AsyncSession, encounter_id: str) -> list[ProgressNote]:
    """按书写时间升序返回该接诊的全部病程记录。"""
    stmt = (
        select(ProgressNote)
        .where(ProgressNote.encounter_id == encounter_id)
        .order_by(ProgressNote.recorded_at)
    )
    return list((await db.execute(stmt)).scalars().all())


# 病程时间允许早于入院多久（小时）。留一点余量：急诊转住院、补录时
# 医生填的时间可能略早于系统记录的入院时刻。
_RECORDED_AT_LEEWAY_HOURS = 24


async def _validate_recorded_at(
    db: AsyncSession, encounter_id: str, value: datetime
) -> None:
    """校验病程时间落在本次住院的合理区间内（2026-08-14 第八轮审计新增）。

    原先 recorded_at 完全不做范围校验（补写场景确实需要医生手填），
    于是入院前、出院后、甚至明年的时间都原样入库，而 list_notes 只按它排序：
    这条会静默排到入院记录之前或整条时间轴最末尾，医生看到的病程顺序与真实
    诊疗过程不符——而**病历时间逻辑正是住院质控的必查项**。

    跨年尤其危险：前端 DatePicker 用 format='MM-DD HH:mm'，**界面上根本不显示
    年份**。2027 年 1 月补写 2026 年 12 月的病程，选出来的是 2027-12-xx，
    输入框显示「12-29 10:00」，与正确值肉眼无法区分。

    Raises:
        HTTPException(400): 时间早于入院过多，或晚于当前时刻。
    """
    now = datetime.now()
    if value > now:
        raise HTTPException(
            status_code=400,
            detail=f"病程时间不能晚于当前时刻（填的是 {value:%Y-%m-%d %H:%M}，"
                   f"请检查年份是否选错）",
        )
    visited_at = (await db.execute(
        select(Encounter.visited_at).where(Encounter.id == encounter_id)
    )).scalar_one_or_none()
    if visited_at is not None:
        earliest = visited_at - timedelta(hours=_RECORDED_AT_LEEWAY_HOURS)
        if value < earliest:
            raise HTTPException(
                status_code=400,
                detail=f"病程时间早于本次入院时间（入院 {visited_at:%Y-%m-%d %H:%M}，"
                       f"填的是 {value:%Y-%m-%d %H:%M}，请检查年份是否选错）",
            )


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
    """新建一条病程记录（默认 status=draft，recorded_at 缺省为当前时间）。

    Raises:
        HTTPException(400): note_type 不在白名单内。
    """
    if note_type not in VALID_NOTE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"note_type 必须是 {sorted(VALID_NOTE_TYPES)} 之一",
        )
    parsed = parse_iso_naive(recorded_at_raw)
    if parsed is not None:
        await _validate_recorded_at(db, encounter_id, parsed)
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
    editor_name: Optional[str] = None,
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
        # ── 署名跟随实际书写人（2026-08-14 第八轮审计修复）──────────────────
        #
        # recorded_by 原先只在 create_note「建空条目」那一刻写死，此后再不更新。
        # 真实形态：白班 A 医生在时间轴点一下「日常病程」建了条空草稿就下班了
        # （前端建的就是 content='' 的立即建条），夜班接手的 B 医生打开它、
        # 写完全部正文、点签发——这条病程的书写医生仍是 A。
        # 签发即整条冻结，此后无法更正；而 recorded_by 是这条病程**唯一**的
        # 署名字段（ProgressNote 没有版本表、没有 triggered_by、没有快照）。
        # 30 天住院里换管床、值班交接是常态，医院硬要求是「病历上写的名字
        # 必须是本人」。谁写的正文就署谁，空正文的占位条不改（没人写过内容）。
        if editor_name and content.strip():
            note.recorded_by = editor_name
    if status is not None:
        note.status = status
    if recorded_at_raw is not None:
        parsed = parse_iso_naive(recorded_at_raw)
        if parsed:
            await _validate_recorded_at(db, encounter_id, parsed)
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
