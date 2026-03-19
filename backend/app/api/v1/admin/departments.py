from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.department import DepartmentCreate, DepartmentResponse
from app.services.department_service import DepartmentService
from app.core.security import require_admin

router = APIRouter()


@router.get("")
async def list_departments(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    service = DepartmentService(db)
    return await service.list_all()


@router.post("", status_code=201)
async def create_department(
    data: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    service = DepartmentService(db)
    return await service.create(data)


@router.delete("/{dept_id}", status_code=204)
async def deactivate_department(
    dept_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    service = DepartmentService(db)
    await service.deactivate(dept_id)
