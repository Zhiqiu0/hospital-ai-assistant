from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from datetime import timedelta
from app.models.user import User
from app.core.security import verify_password, create_access_token
from app.config import settings


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def login(self, username: str, password: str):
        result = await self.db.execute(
            select(User).where(User.username == username).options(selectinload(User.department))
        )
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            return None
        if not user.is_active:
            return None

        token = create_access_token(
            {"sub": user.id, "role": user.role},
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        )

        dept_name = user.department.name if user.department else None

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_minutes * 60,
            "user": {
                "id": user.id,
                "username": user.username,
                "real_name": user.real_name,
                "role": user.role,
                "department_id": user.department_id,
                "department_name": dept_name,
            },
        }

    async def get_login_error(self, username: str, password: str):
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()
        if not user:
            return "账号不存在"
        if not verify_password(password, user.password_hash):
            return "密码不正确"
        if not user.is_active:
            return "账号已被禁用"
        return None

    async def check_username_exists(self, username: str) -> bool:
        result = await self.db.execute(
            select(User.id).where(User.username == username)
        )
        return result.scalar_one_or_none() is not None
