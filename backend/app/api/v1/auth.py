"""
认证路由（/api/v1/auth/*）

提供登录、登出及账号检查端点。
登录接口含限速保护（防爆破），登出时将 JWT 写入黑名单。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
from datetime import datetime, timezone

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings
from app.core.rate_limit import login_limiter
from app.database import get_db
from app.models.revoked_token import RevokedToken
from app.schemas.auth import LoginRequest, TokenResponse
from app.services.audit_service import log_action
from app.services.auth_service import AuthService

_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, http_request: Request, db: AsyncSession = Depends(get_db)):
    # 按用户名限速：防爆破单个账号，不影响同网段其他医生
    login_limiter.check(http_request, key_override=f"login:{request.username}")
    service = AuthService(db)
    result = await service.login(request.username, request.password)
    if not result:
        detail = await service.get_login_error(request.username, request.password)
        await log_action(
            action="login",
            user_name=request.username,
            detail=f"登录失败：{detail or '账号或密码错误'}",
            ip_address=http_request.client.host if http_request.client else None,
            status="error",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail or "登录失败",
        )
    await log_action(
        action="login",
        user_id=result.get("user", {}).get("id") if isinstance(result, dict) else None,
        user_name=request.username,
        detail="登录成功",
        ip_address=http_request.client.host if http_request.client else None,
    )
    return result


@router.post("/logout")
async def logout(
    token: str = Depends(_oauth2),
    db: AsyncSession = Depends(get_db),
):
    if token:
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                db.add(RevokedToken(
                    jti=jti,
                    expires_at=datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None),
                ))
                await db.commit()
        except JWTError:
            pass
    return {"ok": True}


@router.get("/check-username")
async def check_username(username: str, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    exists = await service.check_username_exists(username)
    return {
        "exists": exists,
        "message": "账号存在" if exists else "账号不存在",
    }
