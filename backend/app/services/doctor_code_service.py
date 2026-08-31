# -*- coding: utf-8 -*-
"""HIS 工号绑定管理（services/doctor_code_service.py）

2026-09-01 数据更正流程审计新增。

**为什么必须有**：医院给的是全院名单，里面混着自助机、护工、财务（记忆库里
已记载这个坑），批量开户时把「护工王某」的工号挂到临床医生李某名下是完全可能
发生的。而在此之前，DoctorCode 行**只增不改不删**：
  · `UserUpdate` schema 里没有 employee_no 字段；
  · 全仓对 DoctorCode 零 UPDATE、零 DELETE；
  · 批量开户遇到已被占用的工号直接跳过（「绝不从别人名下抢工号」）。

而 HIS 派单是按 doctor_codes 定位归属、且**归属先于状态**：停用那个错误账号
只会让该工号的推送一律 ack 40007「工号 X 对应的账号已停用，请联系管理员改派
或启用」——**而「改派」这个功能当时并不存在**。结果就是：不停用，病历继续署
错人名；停用，那位医生的病人再也进不了系统。唯一出路是工程师直接改库，而项目
铁律禁止直接 SQL 改数据。

**改绑不追溯历史**：已产生的接诊/病历按 doctor_id 存，不经过 doctor_codes，
所以改绑只影响**此后**的 HIS 推送归属，不会把历史病历的署名追溯性地改掉。
这是刻意的——法定文书签发时是谁就永远是谁。
"""
import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import RECORD_WRITE_ROLES
from app.models.user import DoctorCode, User

logger = logging.getLogger(__name__)


async def _load_code(db: AsyncSession, code: str) -> DoctorCode:
    """按工号取绑定行，不存在即 404。"""
    row = (await db.execute(
        select(DoctorCode).where(DoctorCode.code == code)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"工号 {code} 未绑定任何账号")
    return row


async def _assert_bindable(db: AsyncSession, user_id: str) -> User:
    """目标账号必须能真正接住 HIS 推送，否则改绑只是把问题挪个地方。

    这三条与 his_adapter/admit_service 里定位归属时的判据一一对应：那边任一
    条不满足都会 ack 40007 拒收接诊，患者进不了工作台。在绑定这一刻就拦下来，
    好过等到 HIS 推第一个病人时才发现。
    """
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "目标账号不存在")
    if not user.is_active:
        raise HTTPException(400, f"账号 {user.username} 已停用，不能接收 HIS 推送")
    if user.role not in RECORD_WRITE_ROLES:
        raise HTTPException(
            400,
            f"账号 {user.username} 的角色是 {user.role}，不是临床医生——"
            "HIS 推送到非医生账号会被拒收（ack 40007）",
        )
    return user


async def list_codes(db: AsyncSession, *, user_id: str | None = None,
                     code: str | None = None) -> list[dict]:
    """查工号绑定情况。排障入口：HIS 报 40007 时先来这里看这个工号挂在谁名下。"""
    stmt = select(DoctorCode, User).join(User, User.id == DoctorCode.user_id)
    if user_id:
        stmt = stmt.where(DoctorCode.user_id == user_id)
    if code:
        stmt = stmt.where(DoctorCode.code == code)
    rows = (await db.execute(stmt.order_by(DoctorCode.code))).all()
    return [
        {
            "id": dc.id,
            "code": dc.code,
            "note": dc.note,
            "user_id": u.id,
            "username": u.username,
            "real_name": u.real_name,
            "role": u.role,
            "is_active": u.is_active,
        }
        for dc, u in rows
    ]


async def bind_code(db: AsyncSession, *, user_id: str, code: str,
                    note: str | None = None) -> dict:
    """给账号新增一个工号。

    一位医生挂多个工号是常态（门诊号/住院号/助理号各一个），所以这里是「新增」
    而不是「替换」。工号全局唯一，已被占用时明确报出当前归属——直接告诉操作者
    该去改绑而不是新增，省掉一次来回。
    """
    code = (code or "").strip()
    if not code:
        raise HTTPException(400, "工号不能为空")
    user = await _assert_bindable(db, user_id)

    existing = (await db.execute(
        select(DoctorCode, User).join(User, User.id == DoctorCode.user_id)
        .where(DoctorCode.code == code)
    )).first()
    if existing is not None:
        _, owner = existing
        if owner.id == user_id:
            raise HTTPException(400, f"工号 {code} 已经绑定在该账号下")
        raise HTTPException(
            409,
            f"工号 {code} 当前绑定在 {owner.real_name or owner.username} 名下，"
            "如需转移请用改绑功能（不要新增，工号全局唯一）",
        )

    db.add(DoctorCode(user_id=user_id, code=code, note=note or "后台绑定"))
    await db.commit()
    logger.info("doctor_code.bind: code=%s -> user=%s", code, user_id)
    return {"code": code, "user_id": user_id, "real_name": user.real_name}


async def reassign_code(db: AsyncSession, *, code: str, target_user_id: str) -> dict:
    """把工号从当前账号改绑到另一个账号——本模块存在的主要理由。

    Returns:
        含改绑前后归属的字典，供路由层写进审计日志（谁把哪个工号从谁名下
        转给了谁，这正是事后要还原的东西）。
    """
    row = await _load_code(db, code)
    old_user = await db.get(User, row.user_id)
    if row.user_id == target_user_id:
        raise HTTPException(400, "该工号已经绑定在目标账号下，无需改绑")
    target = await _assert_bindable(db, target_user_id)

    row.user_id = target_user_id
    await db.commit()
    logger.warning(
        "doctor_code.reassign: code=%s %s -> %s（此后该工号的 HIS 推送归新账号）",
        code, old_user.id if old_user else "?", target_user_id,
    )
    return {
        "code": code,
        "from": {"user_id": old_user.id if old_user else None,
                 "real_name": old_user.real_name if old_user else None},
        "to": {"user_id": target.id, "real_name": target.real_name},
    }


async def unbind_code(db: AsyncSession, *, code: str) -> dict:
    """解除工号绑定。

    用于「这个工号根本不该存在」的情形（护工/自助机/财务的号被误导入）。
    解绑后 HIS 再推这个工号会 ack 40007 并在 message 里带上工号——那正是希望
    的行为：让厂商侧发现推错了号，而不是让病历落到某个医生名下。
    """
    row = await _load_code(db, code)
    owner = await db.get(User, row.user_id)
    await db.delete(row)
    await db.commit()
    logger.warning("doctor_code.unbind: code=%s 原属 user=%s", code, row.user_id)
    return {"code": code,
            "was": {"user_id": owner.id if owner else None,
                    "real_name": owner.real_name if owner else None}}
