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

# 手机号统一走 app.core.validators.identity 的类型别名，规则集中维护
from app.core.validators.identity import Phone


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
    phone: Phone = None                  # 手机号（normalize + 11 位号段校验）
    # email 暂不做强校验：项目内 email 字段几乎不用，加 EmailStr 需引入 email-validator
    # 新依赖；若未来用作密码找回/通知则切换 EmailStr（一行字面改动）
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


class BulkImportDoctorItem(BaseModel):
    """批量开户的单条医生记录（2026-08-13）。

    对应医院信息科提供的人员名单一行（或多行合并）：
      real_name : 医生本人姓名——**病历署名用它**，助理工号推来的病历同样署本人名
      codes     : 该医生名下全部 HIS 工号（本人门诊/本人住院/助理），HIS 推任一个
                  都能映射到本账号
      username  : 登录名，默认取 codes[0]（约定「用户名=主工号」）
    """

    real_name: str
    codes: list[str]                       # 至少一个工号
    username: Optional[str] = None         # 缺省用 codes[0]
    department_name: Optional[str] = None  # 科室名（按名匹配已有科室，匹配不上则留空）
    role: str = "doctor"
    phone: Phone = None


class BulkImportRequest(BaseModel):
    """批量开户入参。

    统一初始密码（医院要求便于分发）+ 强制首次登录改密：
    未改密的账号在服务端只能访问改密端点，看不到任何病历/患者数据，
    因此"知道工号就能用初始密码登进别人账号"的风险被消除。
    """

    items: list[BulkImportDoctorItem]
    # 全院统一初始密码。加长度下限（2026-08-13 第三轮审计修复）：原先是裸 str，
    # 管理员传空串就能批量建出空密码账号，而这些账号的用户名=工号（院内公开），
    # 等于一键把全院账号敞开。改密端点要求 ≥6 位，建号入口不该比它更松。
    initial_password: str = Field(default="MediScribe@2026", min_length=6, max_length=128)
    dry_run: bool = False                       # 只校验不落库，供导入前预览


class BulkImportResultItem(BaseModel):
    """单条导入结果。"""

    real_name: str
    username: str
    codes: list[str]
    status: str          # created / skipped_exists / code_conflict / error
    message: Optional[str] = None


class BulkImportResponse(BaseModel):
    """批量开户结果汇总（前端据此展示报表并提示分发初始密码）。"""

    total: int
    created: int
    skipped: int
    failed: int
    initial_password: str
    items: list[BulkImportResultItem]
