"""
管理后台用户管理接口（/api/v1/admin/users/*）

提供用户的增删改查，仅管理员可访问。

安全守卫：
  - 不能停用自己的账号——避免管理员误点把自己锁出系统
  - 分级操作（2026-08-11 审计修复）：低级管理员不能操作等级 ≥ 自己的账号、
    不能授予/自提到高于自己的角色、不能停用或降级唯一在用的超级管理员。
    分级逻辑集中在 _user_authz.py，各写端点在进 UserService 前调用。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.api.v1.admin._user_authz import (
    assert_can_manage_target,
    assert_can_set_role,
    assert_creation_scope,
    assert_not_last_super_admin,
)
from app.core.security import require_admin
from app.database import get_db
from app.schemas.user import (
    BulkImportRequest,
    BulkImportResponse,
    ResetPasswordRequest,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from app.services.user_bulk_import import bulk_import_doctors as bulk_import_doctors_service
from app.services.user_service import UserService

router = APIRouter()


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    service = UserService(db)
    return await service.list_users(page, page_size)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    # 分级守卫：不得创建高于/等于自己权限的账号（防非超管造超管自我提权）
    assert_can_set_role(current_user, data.role)
    # 建号范围守卫（2026-08-29 第七轮渗透审计）：dept_admin 限本科室、
    # 跨科角色与 HIS 工号绑定仅院级可为——详见 assert_creation_scope
    assert_creation_scope(current_user, role=data.role,
                          department_id=data.department_id,
                          employee_no=data.employee_no)
    service = UserService(db)
    return await service.create(data)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    service = UserService(db)
    target = await service.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 不能改自己的角色（防自提权）
    if user_id == current_user.id and data.role is not None and data.role != current_user.role:
        raise HTTPException(status_code=403, detail="不能修改自己的角色")
    # 分级守卫：不能操作等级 ≥ 自己的目标；设新角色不得越级
    await assert_can_manage_target(db, current_user, target)
    if data.role is not None:
        assert_can_set_role(current_user, data.role)
        # 跨科权限角色只能由院级授予（2026-08-29 第十轮收敛验证补口径）：
        # create 路径的 assert_creation_scope 已确立"质控员/影像医师仅院级
        # 可授"，update 通道此前缺同款守卫——dept_admin 可把本科室账号
        # **改**成 qc_officer（=院级质控员，全院已签发病历只读），从修改
        # 侧把建号守卫整个绕开。改角色与授角色是同一动作，同一口径。
        if (data.role in ("qc_officer", "radiologist")
                and data.role != target.role
                and current_user.role not in ("hospital_admin", "super_admin")):
            raise HTTPException(
                status_code=403,
                detail="质控员/影像医师为跨科室权限角色，请联系院级管理员调整")
    # 科室迁移限制（同轮补）：dept_admin 只能在本科室范围内管理，
    # 把账号改到他科等于跨科铸号的变体
    if (data.department_id is not None
            and data.department_id != target.department_id
            and current_user.role == "dept_admin"):
        raise HTTPException(
            status_code=403, detail="科室管理员不能把账号迁往其他科室")
    # 降级唯一在用超管前的存活性守卫
    await assert_not_last_super_admin(
        db, target, will_deactivate=(data.is_active is False), new_role=data.role
    )
    return await service.update(user_id, data)


@router.delete("/{user_id}", status_code=204)
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    # 不允许停用自己——避免管理员误点把自己锁出，需要其他管理员才能操作
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能停用自己的账号，请由其他管理员操作")
    service = UserService(db)
    target = await service.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    await assert_can_manage_target(db, current_user, target)
    await assert_not_last_super_admin(db, target, will_deactivate=True, new_role=None)
    await service.deactivate(user_id)


@router.post("/{user_id}/activate", status_code=204)
async def activate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """重新启用已停用的用户账号（is_active=True）。"""
    service = UserService(db)
    target = await service.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 启用等级 ≥ 自己的账号同样需足够权限（防低级管理员启用超管做跳板）
    await assert_can_manage_target(db, current_user, target)
    await service.activate(user_id)


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """管理员重置用户密码。前端展示新密码一次后用户登录改回。"""
    service = UserService(db)
    target = await service.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 分级守卫：不能给等级 ≥ 自己的账号改密（防夺取超管账号）
    await assert_can_manage_target(db, current_user, target)
    await service.reset_password(user_id, data.new_password)
    # 解锁登录限流（2026-08-13）：医生真忘了密码、连输失败被锁 10 分钟，找信息科
    # 重置后那把锁还在，拿着新密码照样 429——重置的意义就没了。这里一并清零。
    from app.core.rate_limit import login_limiter
    await login_limiter.reset(f"login:{target.username}")
    return {"ok": True}


@router.post("/bulk-import", response_model=BulkImportResponse)
async def bulk_import_doctors(
    data: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """批量开户：按医院人员名单一次性建医生账号（详见 user_bulk_import 服务）。"""
    # 角色分级守卫（2026-08-13 第三轮审计修复）：本端点原先只有 require_admin，
    # 而 require_admin 放行到 dept_admin——低级管理员传 role="super_admin" 就能
    # 造出超管账号，且初始密码是他自己指定的，登录改密即接管全院。
    # 这等于把 PR#89 已修的提权洞开了个新入口。逐条校验，与 create_user 同一守卫。
    for item in data.items:
        assert_can_set_role(current_user, item.role)
    # 批量开户带 HIS 工号（codes），且科室按名字任选——按建号范围守卫的
    # 第 3 条口径，整个批量开户动作仅院级管理员可为（2026-08-29 第七轮审计）
    if current_user.role not in ("hospital_admin", "super_admin"):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403, detail="批量开户（含 HIS 工号绑定）仅院级管理员可操作")
    return await bulk_import_doctors_service(db, data, current_user)
