"""
用户相关 Pydantic 模型（schemas/user.py）

包含：
  UserCreate      : 管理员创建用户的入参
  UserUpdate      : 更新用户信息的入参（所有字段可选）
  UserResponse    : 用户查询响应（不含 password_hash）
  UserListResponse: 用户列表分页响应

安全说明：
  UserResponse 不含 password_hash 字段，防止密码哈希值泄露给前端。
  UserCreate 中的 password 是明文，由服务层 hash 后再存库。
"""

from typing import Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """管理员创建新用户的入参。

    password 字段由管理员设置初始密码，服务层使用 bcrypt 哈希后存储。
    """

    username: str               # 登录用户名（全局唯一）
    password: str               # 初始明文密码（服务层 bcrypt 哈希后存储）
    real_name: str              # 真实姓名（病历署名和界面显示用）
    role: str                   # 角色：doctor / dept_admin / hospital_admin / super_admin
    department_id: Optional[str] = None  # 所属科室 ID（普通医生必填，超级管理员可空）
    employee_no: Optional[str] = None    # 工号（与 HIS 对接用）
    phone: Optional[str] = None
    email: Optional[str] = None


class UserUpdate(BaseModel):
    """更新用户信息的入参（所有字段可选，只更新传入的非 None 字段）。

    注意：不包含 username 和 password 字段，
    修改用户名/密码需使用专门的端点。
    """

    real_name: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[str] = None
    is_active: Optional[bool] = None  # False=禁用账号


class UserResponse(BaseModel):
    """用户查询响应（脱敏，不含密码哈希）。"""

    id: str
    username: str
    real_name: str
    role: str
    is_active: bool               # 账号是否启用
    department_id: Optional[str] = None    # 所属科室 ID
    department_name: Optional[str] = None  # 所属科室名称（冗余字段，减少前端查询）

    class Config:
        from_attributes = True  # 允许从 ORM User 对象直接实例化


class UserListResponse(BaseModel):
    """用户列表分页响应。"""

    total: int
    items: list[UserResponse]


class ResetPasswordRequest(BaseModel):
    """管理员重置用户密码入参（POST /admin/users/{id}/reset-password）。

    密码原文不可"看"——DB 只存 bcrypt 哈希，连后端开发者也看不到。
    管理员只能"重置"：自动生成或手动输入新明文，前端展示一次后让用户首次登录改回。

    new_password 长度由前端校验（建议 ≥ 8 + 包含字母数字）；后端只保证非空。
    """

    new_password: str = Field(min_length=1, max_length=200)
