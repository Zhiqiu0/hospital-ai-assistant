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
    # 主工号（展示用；HIS 映射走 doctor_codes 表，见下方 relationship）
    employee_no: Mapped[Optional[str]] = mapped_column(String(50))
    # 首次登录强制改密（2026-08-13 批量开户）：批量建号用统一初始密码便于分发，
    # 但未改密前 get_current_user 只放行改密端点，其余一律 403——避免"知道工号
    # 就能用初始密码登进别人账号"（工号规律性强、名单在院内流传，可枚举）。
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(100))
    # 软删除标记：禁用账号时设为 False，登录验证会拒绝 is_active=False 的用户
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 最后登录时间（每次成功登录后更新，用于账号活跃度分析）
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # 关联科室（用于界面显示科室名称，不参与业务逻辑）
    department: Mapped[Optional[Department]] = relationship(back_populates="users")
    # 该医生名下的全部 HIS 工号（一人可有多个：本人门诊/本人住院/助理）
    doctor_codes: Mapped[list["DoctorCode"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class DoctorCode(Base, TimestampMixin):
    """医生 HIS 工号（users 1:N doctor_codes）——2026-08-13 批量开户。

    为什么一个账号要挂多个工号（安吉濮氏医院真实名单证实）：
      汪来煜 → 6069(本人·门诊) / 16029(本人·住院) / 16039(助理)
      濮正飞 → 6019(本人) / 6059(助理)
    同一位医生因「门诊/住院」「本人/助理」被 HIS 分配了多个工号，HIS 推接诊时
    可能用其中任一个。原先 User.employee_no 只能存一个，推另一个就映射失败
    （ack 40007，接诊根本进不来）——这是联调必炸的点。

    **病历署名始终是账号的 real_name（本人）**：医院明确要求病历上不能出现助理
    名字。工号只用于识别"这条推送属于哪位医生"，署名一律取账号姓名，助理工号
    推来的病历同样署本人名，天然满足该要求。

    code 全局唯一：一个工号只能属于一位医生，防止导入名单时张冠李戴。
    """

    __tablename__ = "doctor_codes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    # HIS 工号，全局唯一（HIS 推送的 doctor_code 按此匹配）
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    # 备注该工号的用途："本人·门诊" / "本人·住院" / "助理"，便于后台核对与排障
    note: Mapped[Optional[str]] = mapped_column(String(50))

    user: Mapped["User"] = relationship(back_populates="doctor_codes")
