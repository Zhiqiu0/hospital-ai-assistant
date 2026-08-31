# -*- coding: utf-8 -*-
"""重复患者档案合并路由（/api/v1/admin/patient-merge/*）

2026-09-01 数据更正流程审计新增。业务说明与三条设计红线见
services/patient_merge_service.py 的模块文档。

端点：
  GET  /preview?target_id=&source_id=   干跑预览（人眼核对"是不是同一个人"）
  POST /                                执行合并（需逐字确认源档案姓名）

权限：限超管/院级管理员。刻意**不给科室管理员**——合并跨越整份患者档案与
其全部历史接诊，不是某个科室内部的事，而 dept_admin 在本系统里本就没有跨科室
的临床数据职责。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.database import get_db
from app.services import patient_merge_service as svc
from app.services.audit_service import log_action

router = APIRouter()

# 只有这两个角色能合并档案（dept_admin 不在内，理由见模块 docstring）
_MERGE_ROLES = {"super_admin", "hospital_admin"}


class MergeRequest(BaseModel):
    """执行合并入参。"""

    target_id: str          # 保留下来的档案
    source_id: str          # 被合并掉的档案（合并后软删）
    confirm_name: str       # 逐字输入的源档案姓名，防误点
    reason: str             # 合并理由，进审计


def _assert_may_merge(user) -> None:
    if getattr(user, "role", None) not in _MERGE_ROLES:
        raise HTTPException(403, "仅超级管理员/院级管理员可合并患者档案")


@router.get("/preview")
async def preview_merge(
    target_id: str = Query(..., description="保留下来的档案"),
    source_id: str = Query(..., description="将被合并掉的档案"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """干跑预览：两份档案对照 + 将要搬动的数据量 + 风险提示。

    这是执行前唯一的人眼防线。返回的 warnings 里如果出现"两份档案的身份证号
    都存在且不一致"，几乎可以断定是两个不同的人——**立刻停手**。
    """
    _assert_may_merge(current_user)
    return await svc.preview(db, target_id=target_id, source_id=source_id)


@router.post("")
async def merge_patients(
    data: MergeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """执行合并。**不可逆**——误合并两个真实存在的人无法撤销。

    已签发病历的 patient_snapshot 不受影响：它签发瞬间冻结并进了 sign_hash，
    是法定文书上的署名来源，签发时写的是哪个名字就永远是哪个。
    """
    _assert_may_merge(current_user)
    res = await svc.merge(
        db,
        target_id=data.target_id,
        source_id=data.source_id,
        confirm_name=data.confirm_name,
        operator_id=current_user.id,
    )
    # 审计必须能还原"把谁并进了谁、搬了多少数据、为什么"。
    # 只记档案 ID 与姓名（患者姓名在本系统的审计日志里本就是可记录项，
    # 见 patients.py 的 PHI 访问留痕口径），不记病历内容。
    await log_action(
        action="merge_patient",
        user_id=current_user.id,
        user_name=getattr(current_user, "real_name", None)
        or getattr(current_user, "username", None),
        user_role=getattr(current_user, "role", None),
        resource_type="patient",
        resource_id=data.target_id,
        detail=(f"合并档案：{res['source_name']}({data.source_id}) → {data.target_id}，"
                f"搬移接诊 {res['moved']['encounters']} 条、"
                f"影像 {res['moved']['imaging_studies']} 项，"
                f"补空字段 {len(res['filled_fields'])} 个；理由：{data.reason}"),
    )
    return res
