"""
管理后台用户管理接口（/api/v1/admin/users/*）

提供用户的增删改查，仅管理员可访问。

安全守卫（2026-05-03 加）：
  - 不能停用自己的账号——避免管理员误点把自己锁出系统
  - 不能停用唯一的超级管理员——避免全院失去最高权限账号（最小可行版本只拦
    "停用自己"，最后一个 super_admin 守卫属于 P2 后续加）
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
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
    await service.deactivate(user_id)


@router.post("/{user_id}/activate", status_code=204)
async def activate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """重新启用已停用的用户账号（is_active=True）。"""
    service = UserService(db)
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
    await service.reset_password(user_id, data.new_password)
    return {"ok": True}
