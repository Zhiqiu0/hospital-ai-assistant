"""
用户服务（app/services/user_service.py）

职责：
  封装用户账号的管理操作，仅供管理后台（admin 角色）调用：
  - get_by_id   : 按 UUID 查询单个用户（含科室信息）
  - list_users  : 分页查询所有用户列表
  - create      : 新建用户账号（自动哈希密码，校验用户名唯一性）
  - update      : 更新用户信息（不含密码，密码单独管理）
  - deactivate  : 停用账号（软删除，is_active=False，不物理删除保留审计记录）

安全说明：
  密码在 create 时通过 security.hash_password() 做 bcrypt 哈希，
  原始密码不存储，update 时不允许直接设置 password_hash 字段。
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
    """用户数据访问服务，封装用户账号 CRUD 操作（仅管理后台使用）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> User | None:
        """按 UUID 查询用户，同时预加载关联科室信息。

        使用 selectinload 预加载 department，避免后续访问 user.department 时触发隐式查询。

        Returns:
            用户 ORM 对象；不存在时返回 None（由调用方决定是否抛 404）。
        """
        result = await self.db.execute(
            select(User).where(User.id == user_id).options(selectinload(User.department))
        )
        return result.scalar_one_or_none()

    async def list_users(self, page: int, page_size: int):
        """分页查询所有用户列表。

        Args:
            page:      页码（从 1 开始）。
            page_size: 每页条数。

        Returns:
            {"total": 总用户数, "items": [用户信息字典列表]}
        """
        offset = (page - 1) * page_size

        # 先统计总数（用于前端分页控件）
        count_result = await self.db.execute(select(func.count()).select_from(User))
        total = count_result.scalar()

        # 再查当前页数据，同时预加载科室关联
        result = await self.db.execute(
            select(User).options(selectinload(User.department)).offset(offset).limit(page_size)
        )
        items = result.scalars().all()
        return {
            "total": total,
            "items": [self._to_dict(u) for u in items],
        }

    def _to_dict(self, user: User) -> dict:
        """将 User ORM 对象转换为标准响应字典（不含密码哈希）。"""
        return {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "role": user.role,
            "is_active": user.is_active,
            "department_id": user.department_id,
            # department 为 None 时（未分配科室）显示 None
            "department_name": user.department.name if user.department else None,
        }

    async def create(self, data: UserCreate) -> User:
        """新建用户账号。

        校验用户名唯一性后，对明文密码做 bcrypt 哈希再存储。
        用户创建时默认 is_active=True，可通过 deactivate() 停用。

        Raises:
            HTTPException(400): 用户名已被使用。
        """
        # 用户名唯一性校验（数据库层也有 UNIQUE 约束，此处提前给出友好提示）
        existing = await self.db.execute(select(User).where(User.username == data.username))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="用户名已存在")

        user = User(
            username=data.username,
            password_hash=hash_password(data.password),  # 明文密码在此处不可逆哈希
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
        """更新用户信息（只更新传入的非 None 字段）。

        注意：UserUpdate schema 不包含 password 字段，密码修改通过单独的接口处理。
        exclude_none=True 确保只传入的字段被更新，未传入的保持原值。

        Raises:
            HTTPException(404): 用户不存在。
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        for field, value in data.model_dump(exclude_none=True).items():
            setattr(user, field, value)

        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def deactivate(self, user_id: str) -> None:
        """停用用户账号（软删除）。

        设置 is_active=False 而非物理删除，保留账号记录用于历史审计
        （已签发病历的 triggered_by 等外键关联仍然有效）。
        停用后该用户无法登录（AuthService.login() 检查 is_active）。

        Raises:
            HTTPException(404): 用户不存在。
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        user.is_active = False
        await self.db.commit()
