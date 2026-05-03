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
from app.services.redis_cache import redis_cache

_LIST_KEY = "department:list_active"
_LIST_TTL = 300  # 5 分钟，新建/停用时主动失效


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

    async def list_all(self, include_inactive: bool = False):
        """查询科室列表。

        Args:
            include_inactive:
              False（默认）→ 只返回 is_active=True，给接诊页科室下拉用，走 Redis 缓存
              True            → 含已停用的，给后台管理页用（让管理员能看见已停用科室
                                并按需"启用"），不走缓存避免污染默认查询

        Returns:
            {"items": [科室字典列表]}
        """
        if not include_inactive:
            # 只查启用的——业务热路径，走缓存
            cached = await redis_cache.get_json(_LIST_KEY)
            if cached is not None:
                return cached

        stmt = select(Department)
        if not include_inactive:
            stmt = stmt.where(Department.is_active.is_(True))
        result = await self.db.execute(stmt)
        items = result.scalars().all()
        data = {
            "items": [
                {
                    "id": d.id,
                    "name": d.name,
                    "code": d.code,
                    "parent_id": d.parent_id,
                    "is_active": d.is_active,
                }
                for d in items
            ]
        }
        if not include_inactive:
            await redis_cache.set_json(_LIST_KEY, data, ttl=_LIST_TTL)
        return data

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
        await redis_cache.delete(_LIST_KEY)
        return dept

    async def deactivate(self, dept_id: str) -> None:
        """停用科室（软删除）。

        设置 is_active=False 而非物理删除，保留科室记录防止历史接诊的 department_id 外键失效。
        停用后该科室不会出现在接诊页的科室选择列表中（list_all 默认只返回 is_active=True）；
        但后台管理页（list_all(include_inactive=True)）仍能看到，可"启用"恢复。

        Raises:
            HTTPException(404): 科室不存在。
        """
        dept = await self.get_by_id(dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="科室不存在")
        dept.is_active = False
        await self.db.commit()
        await redis_cache.delete(_LIST_KEY)

    async def activate(self, dept_id: str) -> None:
        """重新启用已停用的科室（is_active=True）。

        2026-05-03 加：跟用户管理对齐——之前只能停用无法启用，被停用的科室
        无法在前端接诊页恢复显示。

        Raises:
            HTTPException(404): 科室不存在。
        """
        dept = await self.get_by_id(dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="科室不存在")
        dept.is_active = True
        await self.db.commit()
        await redis_cache.delete(_LIST_KEY)
