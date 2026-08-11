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
    assert_not_last_super_admin,
)
from app.core.security import require_admin
from app.database import get_db
from app.schemas.user import (
    ResetPasswordRequest,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
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
    return {"ok": True}
