"""
认证相关 Pydantic 模型（schemas/auth.py）

包含：
  LoginRequest   : 登录请求入参（用户名 + 密码）
  UserInfo       : 登录成功后返回的用户基本信息（不含密码哈希）
  TokenResponse  : 登录成功的完整响应，含 JWT 令牌和用户信息

安全说明：
  响应中不返回 password_hash，前端只会看到 access_token。
  token_type 固定为 "bearer"，与 HTTP Authorization 头标准对应。
"""

from typing import Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """登录请求入参。

    前端发送 POST /api/v1/auth/login 时使用此结构体。
    password 在服务层使用 bcrypt verify 校验，不会明文存储或日志输出。
    """

    username: str  # 登录用户名（唯一）
    password: str  # 明文密码（仅用于 bcrypt 校验，校验后即丢弃）


class UserInfo(BaseModel):
    """当前登录用户的基本信息（包含在 TokenResponse 中返回给前端）。

    前端从此结构体获取：
      - id            : 用于接口请求中标识操作者
      - role          : 控制前端菜单和操作权限
      - department_id : 决定默认显示哪个科室的数据
    """

    id: str
    username: str
    real_name: str       # 姓名（显示在界面右上角和病历署名）
    role: str            # 角色：doctor / dept_admin / hospital_admin / super_admin
    department_id: Optional[str] = None   # 所属科室 ID
    department_name: Optional[str] = None # 所属科室名称（冗余字段，减少前端二次查询）


class TokenResponse(BaseModel):
    """登录成功的响应体，包含 JWT 访问令牌和用户信息。

    前端收到后：
      1. 将 access_token 存入 authStore（持久化到 localStorage）
      2. 后续所有 API 请求在 Authorization 头附加 Bearer {access_token}
      3. expires_in 秒后 token 过期，需重新登录
    """

    access_token: str    # JWT 字符串（HS256 签名）
    token_type: str = "bearer"  # 固定为 "bearer"，符合 OAuth2 规范
    expires_in: int      # 有效期（秒），通常为 settings.access_token_expire_minutes * 60
    user: UserInfo       # 当前用户基本信息
