"""
住院问题列表子路由（/api/v1/encounters/{id}/problems*）

从 inpatient.py 拆出（Round 5 瘦身）：负责问题/诊断的新增、查询、状态更新与删除。
行为与拆分前逐字一致，路由路径/方法/依赖零改动。本模块自建 router，
由 inpatient.py 主 router 拼回。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.authz import assert_encounter_access
from app.database import get_db
from app.models.inpatient import ProblemItem
from app.services import inpatient_service

router = APIRouter()


# ── Request 模型 ──────────────────────────────────────────────────────────────

class ProblemIn(BaseModel):
    """新增问题请求体。"""
    problem_name: str
    icd_code: Optional[str] = None
    onset_date: Optional[str] = None
    is_primary: bool = False


class ProblemPatch(BaseModel):
    """更新问题状态请求体。"""
    status: Optional[str] = None     # active / resolved
    is_primary: Optional[bool] = None
    icd_code: Optional[str] = None


# ── 问题列表 ──────────────────────────────────────────────────────────────────

@router.post("/encounters/{encounter_id}/problems")
async def add_problem(
    encounter_id: str,
    body: ProblemIn,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """向问题列表新增一条诊断/问题。"""
    await assert_encounter_access(db, encounter_id, current_user)
    item = await inpatient_service.add_problem(
        db,
        encounter_id=encounter_id,
        problem_name=body.problem_name,
        icd_code=body.icd_code,
        onset_date=body.onset_date,
        is_primary=body.is_primary,
        added_by=current_user.real_name or current_user.username,
    )
    return _problem_to_dict(item)


@router.get("/encounters/{encounter_id}/problems")
async def get_problems(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取问题列表（主要诊断优先，活跃问题优先）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    items = await inpatient_service.list_problems(db, encounter_id)
    return {"items": [_problem_to_dict(i) for i in items]}


@router.patch("/encounters/{encounter_id}/problems/{problem_id}")
async def update_problem(
    encounter_id: str,
    problem_id: str,
    body: ProblemPatch,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新问题状态（解决 / 设为主要诊断 / 修改 ICD 码）。"""
    await assert_encounter_access(db, encounter_id, current_user)
    item = await inpatient_service.update_problem(
        db,
        encounter_id=encounter_id,
        problem_id=problem_id,
        status=body.status,
        icd_code=body.icd_code,
        is_primary=body.is_primary,
    )
    return _problem_to_dict(item)


@router.delete("/encounters/{encounter_id}/problems/{problem_id}")
async def delete_problem(
    encounter_id: str,
    problem_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """从问题列表删除一条记录。"""
    await assert_encounter_access(db, encounter_id, current_user)
    await inpatient_service.delete_problem(db, encounter_id, problem_id)
    return {"ok": True}


def _problem_to_dict(p: ProblemItem) -> dict:
    """将 ProblemItem ORM 对象序列化为字典。"""
    return {
        "id": p.id,
        "encounter_id": p.encounter_id,
        "problem_name": p.problem_name,
        "icd_code": p.icd_code,
        "onset_date": p.onset_date,
        "status": p.status,
        "is_primary": p.is_primary,
        "added_by": p.added_by,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }
