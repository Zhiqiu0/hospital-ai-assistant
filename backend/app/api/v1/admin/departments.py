"""
管理后台科室管理接口（/api/v1/admin/departments/*）

端点列表：
  GET    /                 查询所有科室（默认含已停用，给后台管理用）
  POST   /                 新建科室
  DELETE /{dept_id}        停用科室（软删除）
  POST   /{dept_id}/activate  重新启用已停用的科室（2026-05-03 加）

仅管理员可访问（require_admin）。
停用科室不会物理删除，已关联该科室的历史接诊记录仍可查询。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.database import get_db
from app.schemas.department import DepartmentCreate
from app.services.department_service import DepartmentService

router = APIRouter()


@router.get("")
async def list_departments(
    include_inactive: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """查询科室列表。

    后台管理默认 include_inactive=True 让管理员能看到已停用科室并按需"启用"。
    工作台接诊页另有自己的 GET /departments（前台路由）使用默认值（仅启用）。
    """
    service = DepartmentService(db)
    return await service.list_all(include_inactive=include_inactive)


@router.post("", status_code=201)
async def create_department(
    data: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """新建科室。code 字段须全局唯一（数据库有 UNIQUE 约束）。"""
    service = DepartmentService(db)
    return await service.create(data)


@router.delete("/{dept_id}", status_code=204)
async def deactivate_department(
    dept_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """停用科室（软删除：设置 is_active=False，不物理删除）。"""
    service = DepartmentService(db)
    await service.deactivate(dept_id)


@router.post("/{dept_id}/activate", status_code=204)
async def activate_department(
    dept_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """重新启用已停用的科室（is_active=True）。"""
    service = DepartmentService(db)
    await service.activate(dept_id)
