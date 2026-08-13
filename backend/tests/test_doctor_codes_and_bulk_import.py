"""一账号多工号 + 首登强改密 + 批量开户测试（2026-08-13）。

覆盖三条真实场景：
  1. HIS 用「本人住院」或「助理」工号推接诊，都要映射到本人账号（病历署名本人）
  2. 批量开户建出的账号未改密前，除改密端点外一律 403（统一初始密码的安全兜底）
  3. 批量开户幂等：重复导入不覆盖已有账号，工号被占用则跳过不抢
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security import require_admin
from app.database import get_db
from app.main import app
from app.models.user import DoctorCode, User


@pytest_asyncio.fixture
async def patched_audit_session(async_db, monkeypatch):
    """审计日志写独立会话，测试里指回内存库，避免 no such table。"""
    import app.services.audit_service as audit_service

    class _FakeSessionCtx:
        async def __aenter__(self):
            return async_db

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(audit_service, "AsyncSessionLocal", lambda: _FakeSessionCtx())


@pytest_asyncio.fixture
async def admin_api(async_db, patched_audit_session):
    """以超管身份调 admin 接口。"""
    operator = User(username="bulkadmin", password_hash="x", real_name="超管",
                    role="super_admin", is_active=True)
    async_db.add(operator)
    await async_db.commit()
    await async_db.refresh(operator)

    app.dependency_overrides[get_db] = lambda: async_db
    app.dependency_overrides[require_admin] = lambda: operator
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield async_db, ac
    app.dependency_overrides.clear()


# ── 1. 多工号映射 ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_map_doctor_matches_any_of_multiple_codes(async_db):
    """本人门诊/本人住院/助理三个工号，推任一个都命中同一本人账号。"""
    from app.his_adapter.admit_service import _map_doctor

    doctor = User(username="6069", password_hash="x", real_name="汪来煜",
                  role="doctor", employee_no="6069", is_active=True)
    async_db.add(doctor)
    await async_db.flush()
    for code, note in (("6069", "本人门诊"), ("16029", "本人住院"), ("16039", "助理")):
        async_db.add(DoctorCode(user_id=doctor.id, code=code, note=note))
    await async_db.commit()

    for code in ("6069", "16029", "16039"):
        matched = await _map_doctor(async_db, code)
        # 关键断言：助理工号命中的也是本人，署名不会写成助理
        assert matched.id == doctor.id
        assert matched.real_name == "汪来煜"


@pytest.mark.asyncio
async def test_map_doctor_unknown_code_raises(async_db):
    """陌生工号仍按原约定报 40007，不静默落到别的医生名下。"""
    from app.his_adapter.admit_service import AdmitError, _map_doctor

    with pytest.raises(AdmitError) as exc:
        await _map_doctor(async_db, "99999")
    assert exc.value.code == 40007


# ── 2. 首登强改密硬拦 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_must_change_password_blocks_business_paths(async_db):
    """未改密账号访问业务接口 403，访问改密端点放行。"""
    from fastapi import Request

    from app.core.security import _is_password_change_path

    def _req(path: str) -> Request:
        return Request({"type": "http", "method": "GET", "path": path,
                        "headers": [], "query_string": b""})

    assert _is_password_change_path(_req("/api/v1/auth/change-password")) is True
    assert _is_password_change_path(_req("/api/v1/auth/logout")) is True
    assert _is_password_change_path(_req("/api/v1/patients")) is False
    assert _is_password_change_path(_req("/api/v1/medical-records/abc")) is False


# ── 3. 批量开户 ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_bulk_import_creates_account_with_all_codes(admin_api):
    """一条名单记录 → 一个账号 + 多条工号，且标记为待改密。"""
    db, ac = admin_api
    res = await ac.post("/api/v1/admin/users/bulk-import", json={
        "items": [{"real_name": "汪来煜", "codes": ["6069", "16029", "16039"]}],
    })
    assert res.status_code == 200
    body = res.json()
    assert body["created"] == 1 and body["items"][0]["status"] == "created"

    user = (await db.execute(
        select(User).where(User.username == "6069")
    )).scalars().first()
    assert user is not None
    assert user.real_name == "汪来煜"
    assert user.must_change_password is True
    assert user.employee_no == "6069"

    codes = (await db.execute(
        select(DoctorCode).where(DoctorCode.user_id == user.id)
    )).scalars().all()
    assert {c.code for c in codes} == {"6069", "16029", "16039"}


@pytest.mark.asyncio
async def test_bulk_import_is_idempotent(admin_api):
    """重复导入同一名单：第二次全部跳过，不覆盖已有账号密码。"""
    db, ac = admin_api
    payload = {"items": [{"real_name": "张三", "codes": ["7001"]}]}
    first = await ac.post("/api/v1/admin/users/bulk-import", json=payload)
    assert first.json()["created"] == 1

    user = (await db.execute(
        select(User).where(User.username == "7001")
    )).scalars().first()
    original_hash = user.password_hash

    second = await ac.post("/api/v1/admin/users/bulk-import", json=payload)
    body = second.json()
    assert body["created"] == 0 and body["skipped"] == 1
    assert body["items"][0]["status"] == "skipped_exists"

    await db.refresh(user)
    assert user.password_hash == original_hash  # 密码没被重置


@pytest.mark.asyncio
async def test_bulk_import_rejects_code_owned_by_others(admin_api):
    """工号已挂在别人名下 → code_conflict 跳过，绝不改挂（防病历张冠李戴）。"""
    db, ac = admin_api
    await ac.post("/api/v1/admin/users/bulk-import", json={
        "items": [{"real_name": "李四", "codes": ["7002", "7003"]}],
    })
    res = await ac.post("/api/v1/admin/users/bulk-import", json={
        "items": [{"real_name": "王五", "username": "wangwu", "codes": ["7003"]}],
    })
    body = res.json()
    assert body["items"][0]["status"] == "code_conflict"
    assert "7003" in body["items"][0]["message"]

    owner = (await db.execute(
        select(DoctorCode).where(DoctorCode.code == "7003")
    )).scalars().first()
    lisi = (await db.execute(
        select(User).where(User.username == "7002")
    )).scalars().first()
    assert owner.user_id == lisi.id  # 工号仍归李四


@pytest.mark.asyncio
async def test_bulk_import_dry_run_does_not_persist(admin_api):
    """预览模式不落库，且批内重复工号在预览时就报冲突。"""
    db, ac = admin_api
    res = await ac.post("/api/v1/admin/users/bulk-import", json={
        "items": [
            {"real_name": "赵六", "codes": ["8001"]},
            {"real_name": "钱七", "username": "qianqi", "codes": ["8001"]},
        ],
        "dry_run": True,
    })
    body = res.json()
    assert body["created"] == 1 and body["skipped"] == 1
    assert body["items"][1]["status"] == "code_conflict"

    exists = (await db.execute(
        select(User).where(User.username == "8001")
    )).scalars().first()
    assert exists is None  # 预览没落库


# ── 4. 首登改密全链路（真依赖，不打桩）──────────────────────────────────────
@pytest.mark.asyncio
async def test_first_login_flow_blocked_then_unlocked(async_db, patched_audit_session):
    """批量开户账号：拿真 token 打业务接口 403 → 改密 → 解锁。"""
    from app.core.security import create_access_token, hash_password

    user = User(username="9001", password_hash=hash_password("Init@123456"),
                real_name="测试医生", role="doctor", employee_no="9001",
                is_active=True, must_change_password=True)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)

    app.dependency_overrides[get_db] = lambda: async_db
    token = create_access_token({"sub": user.id, "role": user.role})
    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            blocked = await ac.get("/api/v1/patients", headers=headers)
            assert blocked.status_code == 403
            assert blocked.headers.get("X-Must-Change-Password") == "1"

            changed = await ac.post("/api/v1/auth/change-password", headers=headers,
                                    json={"old_password": "Init@123456",
                                          "new_password": "MyOwn@2026"})
            assert changed.status_code == 200

            # 改密会写密码水印作废此前签发的所有 token（含医生自己手上这个），
            # 所以端点换发了新 token，前端要替换掉旧的
            new_token = changed.json()["access_token"]
            assert new_token and new_token != token
            new_headers = {"Authorization": f"Bearer {new_token}"}

            unlocked = await ac.get("/api/v1/patients", headers=new_headers)
            assert unlocked.status_code == 200

            # 安全性质：改密**之前**签发的会话失效——这正是「重置密码能踢掉
            # 泄露会话」的依据。水印是秒级粒度（JWT 的 iat 只精确到秒），
            # 所以用一个 60 秒前签发的 token 来验，对应现实中攻击者的会话；
            # 与改密发生在同一秒的 token 会落在粒度内，属已知且可接受的取舍。
            import time as _time

            from jose import jwt as _jwt

            from app.config import settings as _settings
            stale_token = _jwt.encode(
                {"sub": user.id, "role": user.role, "jti": "stale-test",
                 "iat": int(_time.time()) - 60, "exp": int(_time.time()) + 3600},
                _settings.secret_key, algorithm="HS256",
            )
            stale = await ac.get("/api/v1/patients",
                                 headers={"Authorization": f"Bearer {stale_token}"})
            assert stale.status_code == 401
    finally:
        app.dependency_overrides.clear()

    await async_db.refresh(user)
    assert user.must_change_password is False


@pytest.mark.asyncio
async def test_admin_reset_password_reimposes_change_requirement(async_db):
    """管理员重置密码后重新要求首登改密——否则管理员长期持有该医生的可用凭据。"""
    from app.services.user_service import UserService

    user = User(username="9002", password_hash="x", real_name="被重置医生",
                role="doctor", is_active=True, must_change_password=False)
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)

    await UserService(async_db).reset_password(user.id, "TempPass@123")
    await async_db.refresh(user)
    assert user.must_change_password is True


# ── 5. bcrypt 强度下调 + 存量哈希自动升级（2026-08-13 压测定档）────────────
@pytest.mark.asyncio
async def test_login_upgrades_legacy_bcrypt_hash(async_db):
    """存量 rounds=12 的哈希在登录时被就地升到当前配置强度。

    不做这件事的话，调低 rounds 只惠及新建账号，全院存量账号永远慢——
    参数调了等于没调。
    """
    from passlib.context import CryptContext

    from app.config import settings
    from app.services.auth_service import AuthService

    legacy_ctx = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12)
    legacy_hash = legacy_ctx.hash("MyPass@123")
    assert legacy_hash.startswith("$2b$12$")

    user = User(username="legacyhash", password_hash=legacy_hash,
                real_name="存量医生", role="doctor", is_active=True)
    async_db.add(user)
    await async_db.commit()

    res = await AuthService(async_db).login("legacyhash", "MyPass@123")
    assert res is not None, "存量哈希应能正常登录"

    await async_db.refresh(user)
    assert user.password_hash.startswith(f"$2b${settings.bcrypt_rounds:02d}$"), (
        f"登录后哈希未升级到 rounds={settings.bcrypt_rounds}：{user.password_hash[:7]}"
    )
    # 升级后仍能用同一密码登录（没把哈希写坏）
    assert await AuthService(async_db).login("legacyhash", "MyPass@123") is not None


@pytest.mark.asyncio
async def test_new_password_uses_configured_rounds(async_db):
    """新建/改密产生的哈希直接是配置强度。"""
    from app.config import settings
    from app.core.security import hash_password_async

    h = await hash_password_async("Whatever@123")
    assert h.startswith(f"$2b${settings.bcrypt_rounds:02d}$")


# ── 6. 第三轮审计修复的回归锁（2026-08-13）────────────────────────────────
@pytest.mark.asyncio
async def test_single_create_sets_must_change_password_and_code(async_db):
    """后台单个建号：同样要求首登改密，且工号登记进 doctor_codes。

    原先只有批量开户置 must_change_password、只有批量开户写 doctor_codes——
    管理员手工建的账号既不强制改密，工号也不进映射表（HIS 优先查该表，
    同一工号会因归属二义性把病历派错医生）。
    """
    from app.schemas.user import UserCreate
    from app.services.user_service import UserService

    user = await UserService(async_db).create(UserCreate(
        username="single001", password="Init@123456", real_name="单建医生",
        role="doctor", employee_no="SC001",
    ))
    assert user.must_change_password is True
    codes = (await async_db.execute(
        select(DoctorCode).where(DoctorCode.user_id == user.id)
    )).scalars().all()
    assert {c.code for c in codes} == {"SC001"}


@pytest.mark.asyncio
async def test_single_create_rejects_taken_employee_no(async_db):
    """工号已被别人占用时明确报错，不再静默产生二义性归属。"""
    from fastapi import HTTPException

    from app.schemas.user import UserCreate
    from app.services.user_service import UserService

    svc = UserService(async_db)
    await svc.create(UserCreate(username="owner01", password="Init@123456",
                                real_name="占号医生", role="doctor", employee_no="SC002"))
    with pytest.raises(HTTPException) as exc:
        await svc.create(UserCreate(username="taker01", password="Init@123456",
                                    real_name="抢号医生", role="doctor", employee_no="SC002"))
    assert exc.value.status_code == 400
    assert "已被其他账号占用" in exc.value.detail


@pytest.mark.asyncio
async def test_bulk_import_rejects_short_initial_password(admin_api):
    """初始密码不能低于 6 位——原先是裸 str，空串就能批量建出空密码账号。"""
    _db, ac = admin_api
    res = await ac.post("/api/v1/admin/users/bulk-import", json={
        "items": [{"real_name": "弱密码", "codes": ["WEAK1"]}],
        "initial_password": "",
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_bulk_import_backfills_codes_for_existing_account(admin_api):
    """账号已存在时补挂缺失工号，不动账号本身（2026-08-13 第三轮审计修复）。

    原先整条跳过，而全系统只有批量开户会写 doctor_codes——联调期手工建的试点
    账号永远补不上「本人住院/助理」工号，HIS 用它们推接诊直接 ack 40007。
    """
    db, ac = admin_api
    # 先建只有主工号的账号
    await ac.post("/api/v1/admin/users/bulk-import", json={
        "items": [{"real_name": "老账号", "codes": ["EX001"]}],
    })
    user = (await db.execute(select(User).where(User.username == "EX001"))).scalars().first()
    original_hash = user.password_hash

    # 同名单再跑一次，这次带上住院/助理工号
    res = await ac.post("/api/v1/admin/users/bulk-import", json={
        "items": [{"real_name": "老账号", "codes": ["EX001", "EX002", "EX003"]}],
    })
    item = res.json()["items"][0]
    assert item["status"] == "skipped_exists"
    assert "EX002" in item["message"] and "EX003" in item["message"]

    codes = (await db.execute(
        select(DoctorCode).where(DoctorCode.user_id == user.id)
    )).scalars().all()
    assert {c.code for c in codes} == {"EX001", "EX002", "EX003"}

    await db.refresh(user)
    assert user.password_hash == original_hash  # 账号本身没被改动
