"""
用户与科室 ORM 模型（models/user.py）

数据表：
  departments : 科室表，支持父子层级（parent_id 自引用）
  users       : 系统用户表（医生、护士、管理员等）

角色说明（User.role 字段）：
  - super_admin    : 超级管理员，可管理所有医院数据
  - hospital_admin : 医院管理员，管理本院数据
  - dept_admin     : 科室管理员，管理本科室数据
  - doctor         : 普通医生，只能访问自己的接诊记录
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, generate_uuid


class Department(Base, TimestampMixin):
    """科室表。

    支持树形层级：parent_id 指向上级科室（如"外科"下有"普外科"、"骨科"）。
    顶级科室的 parent_id 为 NULL。
    """

    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 科室显示名称，如"心内科"、"急诊科"
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 科室唯一编码，用于系统内部标识，如 "cardiology"、"emergency"
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    # 上级科室 ID（可空，NULL 表示顶级科室）
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"))
    # 软删除标记：is_active=False 时科室不再出现在选择列表中
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 反向关联：该科室下的所有用户
    users: Mapped[list["User"]] = relationship(back_populates="department")


class User(Base, TimestampMixin):
    """系统用户表（医生、管理员等所有使用系统的人员）。

    认证说明：
      密码以 bcrypt 哈希存储（password_hash），明文密码不进入数据库。
      JWT 中的 sub 字段存储 user.id，role 字段存储 user.role。
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    # 登录用用户名，全局唯一
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    # bcrypt 哈希后的密码，长度固定约 60 字符，预留 255 防止算法升级
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 真实姓名，用于病历署名和界面显示
    real_name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 角色：super_admin / hospital_admin / dept_admin / doctor
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # 所属科室（可空，管理员可能不属于具体科室）
    department_id: Mapped[Optional[str]] = mapped_column(ForeignKey("departments.id"))
    # 员工工号（可选，用于与 HIS 系统对接）
    employee_no: Mapped[Optional[str]] = mapped_column(String(50))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(100))
    # 软删除标记：禁用账号时设为 False，登录验证会拒绝 is_active=False 的用户
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 最后登录时间（每次成功登录后更新，用于账号活跃度分析）
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 关联科室（用于界面显示科室名称，不参与业务逻辑）
    department: Mapped[Optional[Department]] = relationship(back_populates="users")
