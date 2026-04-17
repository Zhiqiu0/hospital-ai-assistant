"""
认证路由（/api/v1/auth/*）

端点列表：
  POST /login           用户名密码登录，返回 JWT
  POST /logout          退出登录，将 JWT 写入黑名单（revoked_tokens 表）
  GET  /check-username  查询用户名是否已存在（注册/创建用户前的唯一性校验）

安全机制：
  - 登录接口按用户名维度限速（login_limiter），防止单账号暴力枚举密码
  - 登出时将 JWT 的 jti（JWT ID）写入 revoked_tokens 表（黑名单），
    即使 token 未过期也无法继续使用（get_current_user 每次校验黑名单）
  - 登录成功/失败均记录审计日志（含 IP 地址），便于安全事件溯源
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

# OAuth2 scheme：auto_error=False 使 logout 在无 token 时不报错（幂等）
_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, http_request: Request, db: AsyncSession = Depends(get_db)):
    """用户登录，验证凭据后返回 JWT 访问令牌。

    安全机制：
      - 按用户名限速：同一账号短时间内登录失败次数过多触发 429（防爆破单账号）
      - 不按 IP 限速：避免同一局域网多个医生同时登录时误伤
      - 失败时调用 get_login_error 获取具体错误描述（账号不存在/密码错误/账号停用），
        但只在确认非爆破（已通过限速）后才向前端暴露具体原因
    """
    # 按用户名维度限速：防爆破单个账号，不影响同网段其他医生
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

    # 登录成功：记录审计日志（user_id 从 result 中取）
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
    """退出登录：将当前 JWT 写入黑名单，立即使其失效。

    即使 token 未过期，后续请求校验时 get_current_user 会查询 revoked_tokens 表，
    发现 jti 在黑名单中就拒绝访问。

    无 token 时直接返回 {"ok": True}（幂等，前端已清除 token 的情况下也安全）。
    """
    if token:
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                # 将 jti 写入黑名单，expires_at 用于定期清理过期条目
                db.add(RevokedToken(
                    jti=jti,
                    expires_at=datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None),
                ))
                await db.commit()
        except JWTError:
            pass  # token 已无效（格式错误/签名不符），无需加黑名单
    return {"ok": True}


@router.get("/check-username")
async def check_username(username: str, db: AsyncSession = Depends(get_db)):
    """查询用户名是否已存在（注册/管理员创建用户前的唯一性校验）。

    Returns:
        {"exists": bool, "message": "账号存在" | "账号不存在"}
    """
    service = AuthService(db)
    exists = await service.check_username_exists(username)
    return {
        "exists": exists,
        "message": "账号存在" if exists else "账号不存在",
    }
