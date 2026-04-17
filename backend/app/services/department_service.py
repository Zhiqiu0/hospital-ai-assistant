"""
科室服务（app/services/department_service.py）

职责：
  封装科室的查询、创建和停用操作：
  - get_by_id  : 按 UUID 查询单个科室
  - list_all   : 查询所有启用状态的科室（用于接诊页科室选择列表）
  - create     : 新建科室
  - deactivate : 停用科室（软删除，is_active=False）

科室树结构：
  Department 模型支持 parent_id 字段构建多级科室树（如"内科 → 心内科"）。
  list_all 返回扁平列表，前端根据 parent_id 自行组装树形结构。
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Department
from app.schemas.department import DepartmentCreate


class DepartmentService:
    """科室数据访问服务，封装科室 CRUD 操作。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, dept_id: str) -> Department | None:
        """按 UUID 查询科室。

        Returns:
            科室 ORM 对象；不存在时返回 None（由调用方决定是否抛 404）。
        """
        result = await self.db.execute(select(Department).where(Department.id == dept_id))
        return result.scalar_one_or_none()

    async def list_all(self):
        """查询所有已启用的科室列表。

        仅返回 is_active=True 的科室，已停用的科室不出现在接诊页的科室选择下拉列表中。
        前端根据 parent_id 字段自行组装树形选择器。

        Returns:
            {"items": [Department ORM 对象列表]}
        """
        result = await self.db.execute(
            select(Department).where(Department.is_active.is_(True))
        )
        items = result.scalars().all()
        return {"items": items}

    async def create(self, data: DepartmentCreate) -> Department:
        """新建科室。

        code 字段在数据库层有 UNIQUE 约束，重复写入时会抛出数据库异常，
        调用方（路由层）应捕获 IntegrityError 并返回友好错误信息。

        Args:
            data: 科室创建入参（name、code、parent_id）。

        Returns:
            新创建的 Department ORM 对象。
        """
        dept = Department(name=data.name, code=data.code, parent_id=data.parent_id)
        self.db.add(dept)
        await self.db.commit()
        await self.db.refresh(dept)
        return dept

    async def deactivate(self, dept_id: str) -> None:
        """停用科室（软删除）。

        设置 is_active=False 而非物理删除，保留科室记录防止历史接诊的 department_id 外键失效。
        停用后该科室不会出现在接诊页的科室选择列表中（list_all 只返回 is_active=True）。

        Raises:
            HTTPException(404): 科室不存在。
        """
        dept = await self.get_by_id(dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="科室不存在")
        dept.is_active = False
        await self.db.commit()
