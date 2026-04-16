"""
管理后台用户管理接口（/api/v1/admin/users/*）

提供用户的增删改查，仅管理员可访问。
"""

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import require_admin
from app.database import get_db
from app.schemas.user import UserCreate, UserListResponse, UserResponse, UserUpdate
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
    service = UserService(db)
    await service.deactivate(user_id)
