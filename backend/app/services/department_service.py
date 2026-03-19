from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.user import Department
from app.schemas.department import DepartmentCreate
from fastapi import HTTPException


class DepartmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, dept_id: str) -> Department | None:
        result = await self.db.execute(select(Department).where(Department.id == dept_id))
        return result.scalar_one_or_none()

    async def list_all(self):
        result = await self.db.execute(select(Department).where(Department.is_active == True))
        items = result.scalars().all()
        return {"items": items}

    async def create(self, data: DepartmentCreate) -> Department:
        dept = Department(name=data.name, code=data.code, parent_id=data.parent_id)
        self.db.add(dept)
        await self.db.commit()
        await self.db.refresh(dept)
        return dept

    async def deactivate(self, dept_id: str) -> None:
        dept = await self.get_by_id(dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="科室不存在")
        dept.is_active = False
        await self.db.commit()
