# -*- coding: utf-8 -*-
"""HIS 工号绑定管理路由（/api/v1/admin/doctor-codes/*）

2026-09-01 数据更正流程审计新增。业务说明与「为什么必须有」见
services/doctor_code_service.py 的模块文档。

端点：
  GET    /                    查工号绑定（?user_id= 或 ?code=），排障入口
  POST   /                    给账号新增工号
  PUT    /{code}/reassign     改绑到另一个账号 ← 本模块存在的主要理由
  DELETE /{code}              解除绑定（误导入的护工/自助机工号）

审计：admin 聚合路由已挂 audit_admin_action（记 method+path），但工号归属
变更必须能还原「谁把哪个工号从谁名下转给了谁」，所以这里再显式写一条带内容
的审计——只记工号与账号标识，不记任何患者信息。
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.admin._user_authz import assert_can_manage_target
from app.core.security import require_admin
from app.database import get_db
from app.models.user import User
from app.services import doctor_code_service as svc
from app.services.audit_service import log_action

router = APIRouter()


class BindRequest(BaseModel):
    """新增工号入参。"""

    user_id: str
    code: str
    note: str | None = None


class ReassignRequest(BaseModel):
    """改绑入参。reason 必填——工号归属变更要能事后说清为什么。"""

    target_user_id: str
    reason: str


async def _audit(operator, action: str, detail: str, resource_id: str) -> None:
    """写一条带内容的审计。"""
    await log_action(
        action=action,
        user_id=operator.id,
        user_name=getattr(operator, "real_name", None) or getattr(operator, "username", None),
        user_role=getattr(operator, "role", None),
        resource_type="doctor_code",
        resource_id=resource_id,
        detail=detail,
    )


async def _assert_may_touch(db: AsyncSession, operator: User, user_id: str) -> None:
    """操作涉及的账号必须在操作者的管理范围内。

    与改密/停用同一道守卫：科室管理员不能借工号改绑去动权限等级不低于自己的
    账号（否则等于绕过 _user_authz 的分级控制）。
    """
    target = await db.get(User, user_id)
    if target is not None:
        await assert_can_manage_target(db, operator, target)


@router.get("")
async def list_doctor_codes(
    user_id: str | None = Query(default=None, description="按账号筛选"),
    code: str | None = Query(default=None, description="按工号精确查"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """查工号绑定情况。HIS 报 40007 时先来这里看这个工号挂在谁名下。"""
    return await svc.list_codes(db, user_id=user_id, code=code)


@router.post("", status_code=201)
async def bind_doctor_code(
    data: BindRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """给账号新增一个工号（一位医生挂门诊号/住院号/助理号是常态）。"""
    await _assert_may_touch(db, current_user, data.user_id)
    res = await svc.bind_code(db, user_id=data.user_id, code=data.code, note=data.note)
    await _audit(current_user, "bind_doctor_code",
                 f"绑定工号 {res['code']} 到 {res['real_name']}（{data.note or '后台绑定'}）",
                 res["code"])
    return res


@router.put("/{code}/reassign")
async def reassign_doctor_code(
    code: str,
    data: ReassignRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """把工号改绑到另一个账号。

    注意改绑**不追溯历史**：已产生的接诊与病历按 doctor_id 存储，不经过
    doctor_codes，所以此前那些病历的署名不会被改掉（法定文书签发时是谁就
    永远是谁）。本操作只影响此后 HIS 推送的归属判定。
    """
    row = await svc.list_codes(db, code=code)
    if row:
        await _assert_may_touch(db, current_user, row[0]["user_id"])
    await _assert_may_touch(db, current_user, data.target_user_id)

    res = await svc.reassign_code(db, code=code, target_user_id=data.target_user_id)
    await _audit(
        current_user, "reassign_doctor_code",
        f"工号 {res['code']} 由 {res['from']['real_name']} 改绑至 "
        f"{res['to']['real_name']}；理由：{data.reason}",
        res["code"],
    )
    return res


@router.delete("/{code}")
async def unbind_doctor_code(
    code: str,
    reason: str = Query(..., description="解绑理由，必填"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """解除工号绑定（用于误导入的护工/自助机/财务工号）。

    解绑后 HIS 再推这个工号会 ack 40007 并在 message 里带上工号——这正是希望
    的行为：让厂商侧发现推错了号，而不是让病历落到某个医生名下。
    """
    row = await svc.list_codes(db, code=code)
    if row:
        await _assert_may_touch(db, current_user, row[0]["user_id"])
    res = await svc.unbind_code(db, code=code)
    await _audit(current_user, "unbind_doctor_code",
                 f"解绑工号 {res['code']}（原属 {res['was']['real_name']}）；理由：{reason}",
                 res["code"])
    return res
