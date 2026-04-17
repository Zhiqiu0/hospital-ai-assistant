"""
管理后台科室管理接口（/api/v1/admin/departments/*）

端点列表：
  GET    /            查询所有启用科室列表
  POST   /            新建科室
  DELETE /{dept_id}   停用科室（软删除）

仅管理员可访问（require_admin）。
停用科室不会物理删除，已关联该科室的历史接诊记录仍可查询。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin
from app.database import get_db
from app.schemas.department import DepartmentCreate
from app.services.department_service import DepartmentService

router = APIRouter()


@router.get("")
async def list_departments(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """查询所有启用状态的科室列表（is_active=True）。"""
    service = DepartmentService(db)
    return await service.list_all()


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
