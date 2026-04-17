"""
安全工具模块（core/security.py）

提供以下功能：
  - 密码哈希与验证（bcrypt）
  - JWT 访问令牌的生成与解码
  - 短期音频资源令牌（audio token）的生成与验证
  - FastAPI 依赖：get_current_user、require_admin

音频令牌设计说明（Bug B 修复）：
  HTML <audio> 元素不支持自定义请求头，因此音频 URL 必须携带凭证。
  原做法是把完整会话 JWT 放入 query 参数，会导致 token 写入服务器日志。
  改进后：
    1. 前端先调用 GET /voice-records/{id}/audio-token 获取短期音频令牌
    2. 音频令牌仅含 aud="audio" + resource_id，有效期 5 分钟
    3. 即使 URL 被日志记录，5 分钟后自动失效，且只能访问该特定音频
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

# bcrypt 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 Bearer token 提取器，指向登录端点
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# 音频短期令牌的受众标识，与普通用户 token 区分
_AUDIO_TOKEN_AUDIENCE = "audio"

# 音频令牌有效期（分钟）
_AUDIO_TOKEN_EXPIRE_MINUTES = 5


def hash_password(password: str) -> str:
    """使用 bcrypt 对明文密码进行哈希。"""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与 bcrypt 哈希是否匹配。"""
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """生成 JWT 访问令牌（用于标准 API 请求）。

    Args:
        data:          要编码的载荷，通常包含 sub（用户 ID）、role 等。
        expires_delta: 有效期，默认读取 settings.access_token_expire_minutes。

    Returns:
        HS256 签名的 JWT 字符串。
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    # jti（JWT ID）用于支持令牌吊销，每次生成唯一值
    to_encode.update({"exp": expire, "jti": str(uuid.uuid4())})
    return jwt.encode(to_encode, settings.secret_key, algorithm="HS256")


def create_audio_token(user_id: str, voice_record_id: str) -> str:
    """生成短期音频资源令牌（用于 <audio> 元素的 URL 鉴权）。

    与普通访问令牌的区别：
      - aud = "audio"（受众字段限定只能访问音频端点）
      - sub = voice_record_id（限定只能访问该音频文件）
      - uid = user_id（记录请求来源用户，供审计）
      - 有效期仅 5 分钟，减小令牌泄露后的暴露窗口

    Args:
        user_id:         发起请求的用户 ID。
        voice_record_id: 要访问的语音记录 ID。

    Returns:
        短期 HS256 JWT 字符串。
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=_AUDIO_TOKEN_EXPIRE_MINUTES)
    payload = {
        "aud": _AUDIO_TOKEN_AUDIENCE,  # 受众：仅限音频端点
        "sub": voice_record_id,         # 主题：限定具体音频资源
        "uid": user_id,                 # 发起用户（审计用）
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def verify_audio_token(token: str) -> tuple[str, str]:
    """验证音频短期令牌，返回 (user_id, voice_record_id)。

    Args:
        token: 音频令牌字符串。

    Returns:
        (user_id, voice_record_id) 元组。

    Raises:
        HTTPException 401: token 无效、过期或受众不匹配。
    """
    try:
        # 必须指定 audience，防止普通用户 token 被当作音频 token 使用
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience=_AUDIO_TOKEN_AUDIENCE,
        )
        voice_record_id: str = payload.get("sub", "")
        user_id: str = payload.get("uid", "")
        if not voice_record_id or not user_id:
            raise HTTPException(status_code=401, detail="无效音频令牌")
        return user_id, voice_record_id
    except JWTError:
        raise HTTPException(status_code=401, detail="音频令牌无效或已过期")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """FastAPI 依赖：从 Bearer token 中提取并验证当前用户。

    验证流程：
      1. 解码 JWT，取出 sub（用户 ID）
      2. 查 revoked_tokens 表确认 jti 未被吊销
      3. 从数据库加载用户记录，确认账号处于激活状态

    Returns:
        当前已认证的 User ORM 对象。

    Raises:
        HTTPException 401: token 无效、已吊销或用户不存在/未激活。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    # 检查 token 是否已被吊销（登出后 jti 会写入 revoked_tokens 表）
    jti = payload.get("jti")
    if jti:
        from app.models.revoked_token import RevokedToken
        revoked = await db.get(RevokedToken, jti)
        if revoked:
            raise credentials_exception

    from app.services.user_service import UserService
    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user or not user.is_active:
        raise credentials_exception
    return user


async def require_admin(current_user=Depends(get_current_user)):
    """FastAPI 依赖：要求当前用户具有管理员角色。

    允许角色：super_admin、hospital_admin、dept_admin。

    Raises:
        HTTPException 403: 当前用户角色不满足要求。
    """
    if current_user.role not in ("super_admin", "hospital_admin", "dept_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user
