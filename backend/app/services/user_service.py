"""
用户服务（app/services/user_service.py）

提供用户的查询、创建、更新和停用操作，仅供管理后台调用。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    """用户数据访问服务，封装用户 CRUD 操作。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.id == user_id).options(selectinload(User.department))
        )
        return result.scalar_one_or_none()

    async def list_users(self, page: int, page_size: int):
        offset = (page - 1) * page_size
        count_result = await self.db.execute(select(func.count()).select_from(User))
        total = count_result.scalar()
        result = await self.db.execute(
            select(User).options(selectinload(User.department)).offset(offset).limit(page_size)
        )
        items = result.scalars().all()
        return {
            "total": total,
            "items": [self._to_dict(u) for u in items]
        }

    def _to_dict(self, user: User) -> dict:
        return {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "role": user.role,
            "is_active": user.is_active,
            "department_id": user.department_id,
            "department_name": user.department.name if user.department else None,
        }

    async def create(self, data: UserCreate) -> User:
        existing = await self.db.execute(select(User).where(User.username == data.username))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="用户名已存在")
        user = User(
            username=data.username,
            password_hash=hash_password(data.password),
            real_name=data.real_name,
            role=data.role,
            department_id=data.department_id,
            employee_no=data.employee_no,
            phone=data.phone,
            email=data.email,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update(self, user_id: str, data: UserUpdate) -> User:
        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(user, field, value)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def deactivate(self, user_id: str) -> None:
        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        user.is_active = False
        await self.db.commit()
