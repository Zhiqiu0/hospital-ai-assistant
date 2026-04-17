"""
认证服务（services/auth_service.py）

职责：
  封装用户登录的核心业务逻辑：
  - 校验用户名和密码
  - 检查账号状态（是否被禁用）
  - 生成 JWT 访问令牌
  - 返回标准化的登录响应或分类错误信息

与路由层的分工：
  路由层（auth.py）负责限流校验（RateLimiter）和 HTTP 响应格式；
  AuthService 只做数据库查询和业务判断，不感知 HTTP 层。
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.security import create_access_token, verify_password
from app.models.user import User


class AuthService:
    """认证服务：处理用户登录和用户名查重。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def login(self, username: str, password: str):
        """执行用户登录，返回 token 和用户信息，失败时返回 None。

        查询流程：
          1. 按 username 精确查询用户（同时预加载 department 关系，避免二次查询）
          2. 校验密码哈希
          3. 确认账号未被禁用
          4. 生成 JWT 并组装响应

        Args:
            username: 登录用户名。
            password: 明文密码。

        Returns:
            登录成功时返回含 access_token 和 user 信息的字典；
            任一步骤失败时返回 None（统一由路由层返回 401）。
        """
        result = await self.db.execute(
            # selectinload 预加载 department 关系，避免 N+1 查询
            select(User).where(User.username == username).options(selectinload(User.department))
        )
        user = result.scalar_one_or_none()

        # 用户不存在、密码不匹配、账号被禁用——统一返回 None，不暴露具体原因
        if not user or not verify_password(password, user.password_hash):
            return None
        if not user.is_active:
            return None

        # 生成 JWT，payload 包含 sub（用户 ID）和 role（权限控制）
        token = create_access_token(
            {"sub": user.id, "role": user.role},
            expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        )

        dept_name = user.department.name if user.department else None

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.access_token_expire_minutes * 60,  # 秒
            "user": {
                "id": user.id,
                "username": user.username,
                "real_name": user.real_name,
                "role": user.role,
                "department_id": user.department_id,
                "department_name": dept_name,
            },
        }

    async def get_login_error(self, username: str, password: str) -> str | None:
        """分析登录失败原因，返回具体错误描述。

        与 login() 的区别：login() 统一返回 None 不泄露原因（对外），
        此方法用于限流后向用户展示友好提示（此时已确认非爆破攻击）。

        Returns:
            错误描述字符串；如果实际能登录成功则返回 None。
        """
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
        """检查用户名是否已被使用（用于注册/创建用户时的唯一性校验）。"""
        result = await self.db.execute(
            select(User.id).where(User.username == username)
        )
        return result.scalar_one_or_none() is not None
