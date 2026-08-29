"""管理员分级操作守卫（admin/_user_authz.py）

2026-08-11 安全审计修复：admin 用户管理端点此前只挂 require_admin，
super_admin / hospital_admin / dept_admin 一视同仁 → 低级管理员可给超管改密、
把自己提权为 super_admin、停用唯一超管。本模块统一做「操作者 vs 目标 + 目标角色」
的分级校验，供 users.py 各端点在进 UserService 前调用。

角色等级（数值越大权限越高）：
  super_admin(3) > hospital_admin(2) > dept_admin(1) > doctor/nurse(0)

核心规则：
  1. 不能操作等级 ≥ 自己的目标用户（改密/改角色/停用），管理超管仅超管可为
  2. 不得把角色设为高于自己的等级；非 super_admin 不得写 role=super_admin
  3. 停用/降级 super_admin 前必须保证系统还留有至少一个在用的 super_admin
"""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

# 合法角色枚举（写入前校验，防脏角色入库）——收口引用 authz.ALL_ROLES
# （2026-08-21 阶段0）：此前这里独立手写一份，radiologist 曾漏列导致
# assert_can_set_role 拒绝一切影像科账号（2026-08-14 第六轮审计修复）。
# 角色集合的唯一权威在 core/authz.py，这里只引用不定义。
from app.core.authz import ALL_ROLES as VALID_ROLES

# 角色等级表：管理类三级 + 普通用户。未知角色按最低(0)处理，天然不越权
_ROLE_LEVEL = {"super_admin": 3, "hospital_admin": 2, "dept_admin": 1, "doctor": 0, "nurse": 0}


def role_level(role: str) -> int:
    """取角色等级；未知角色按 0（最低），避免脏数据被误判为高权限。"""
    return _ROLE_LEVEL.get(role, 0)


async def _count_active_super_admins(db: AsyncSession) -> int:
    """统计在用的超级管理员数量（停用/降级唯一超管的守卫用）。"""
    return (await db.execute(
        select(func.count()).select_from(User).where(
            User.role == "super_admin", User.is_active.is_(True)
        )
    )).scalar() or 0


def _assert_valid_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"非法角色：{role}")


def assert_can_set_role(operator: User, new_role: str) -> None:
    """创建/更新时设置角色的守卫：不得设成高于自己的等级，超管角色仅超管能授。"""
    _assert_valid_role(new_role)
    if role_level(new_role) >= role_level(operator.role) and operator.role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="不能创建/授予不低于自己权限等级的角色",
        )
    if new_role == "super_admin" and operator.role != "super_admin":
        raise HTTPException(status_code=403, detail="只有超级管理员能授予超级管理员角色")


def assert_creation_scope(operator: "User", *, role: str,
                          department_id, employee_no) -> None:
    """建号范围守卫（2026-08-29 第七轮渗透审计）。

    assert_can_manage_target 早已确立不变量「科室管理员只能管理本科室的账号」，
    但**创建路径**只比角色等级不看科室——dept_admin 可在任意科室建号、可建
    无科室的 qc_officer（= 院级质控员，全院已签发病历只读）、还能给未开户的
    真实医生抢注 HIS 工号（admit 派工按 employee_no/username 映射，等于把
    那位医生的患者全部截到自己控制的账号）。创建路径按同一不变量收口：
      1. dept_admin 建号强制落在本科室；
      2. qc_officer/radiologist 这类跨科室权限角色仅 hospital_admin 以上可授；
      3. dept_admin 建号不得携带 HIS 工号（employee_no/codes），配工号属
         院级开户动作（批量开户本来就是 hospital_admin 的流程）。
    """
    if operator.role in ("hospital_admin", "super_admin"):
        return
    # 走到这里 operator 只可能是 dept_admin（require_admin + set_role 已过滤）
    if role in ("qc_officer", "radiologist"):
        raise HTTPException(
            status_code=403,
            detail="质控员/影像医师为跨科室权限角色，请联系院级管理员开户")
    op_dept = getattr(operator, "department_id", None)
    if not op_dept or department_id != op_dept:
        raise HTTPException(
            status_code=403, detail="科室管理员只能在本科室创建账号")
    if employee_no:
        raise HTTPException(
            status_code=403,
            detail="HIS 工号绑定属院级开户动作，请联系院级管理员配置")


async def assert_can_manage_target(
    db: AsyncSession, operator: User, target: User,
) -> None:
    """改密/停用/改角色前：不能操作等级 ≥ 自己的目标（管理超管仅超管可为）。"""
    if target.id == operator.id:
        return  # 操作自己由各端点单独按动作判定（如禁止停用自己）
    if role_level(target.role) >= role_level(operator.role) and operator.role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="无权操作权限等级不低于自己的账号",
        )

    # 科室范围限制（2026-08-14 第六轮审计修复）：原先守卫只比**角色等级**、
    # 完全不看科室——dept_admin 实际等于全院管理员，能重置任意科室医生的密码。
    # 而重置密码后那个账号就要用管理员知道的临时密码登录，等于跨科室接管账号，
    # 之后以那位医生的名义签发病历。"科室管理员"这个角色名本身就界定了范围。
    # hospital_admin / super_admin 是全院角色，不受此限。
    if operator.role == "dept_admin":
        op_dept = getattr(operator, "department_id", None)
        tg_dept = getattr(target, "department_id", None)
        if not op_dept or op_dept != tg_dept:
            raise HTTPException(
                status_code=403,
                detail="科室管理员只能管理本科室的账号",
            )


async def assert_not_last_super_admin(
    db: AsyncSession, target: User, *, will_deactivate: bool, new_role: str | None,
) -> None:
    """停用或降级 super_admin 时，保证系统仍留有至少一个在用超管。"""
    if target.role != "super_admin" or not target.is_active:
        return
    demoting = new_role is not None and new_role != "super_admin"
    if (will_deactivate or demoting) and await _count_active_super_admins(db) <= 1:
        raise HTTPException(
            status_code=400,
            detail="系统必须保留至少一个在用的超级管理员，操作被拒绝",
        )
