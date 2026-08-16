"""工作台叫号队列 API（/api/v1/his/queue/*）

2026-08-11 业务联动冲刺——「数据两条腿」：
  GET  /his/queue/today  : 开页拉取今日 HIS 接诊队列（DB 权威数据，断线重连后重拉）
  POST /his/queue/stream : SSE 长连接，实时推送叫号/回写结果事件（事件总线跨 worker）

受 require_his_enabled 保险丝守门（未开 HIS 对接时 503，前端据此隐藏叫号面板）。
鉴权用医生登录态（get_current_user），只推/只查本医生自己的接诊。
"""
import asyncio
import json
import logging
from datetime import date, datetime, time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, is_token_revoked, oauth2_scheme
from app.database import get_db
from app.his_adapter.depends import require_his_enabled
from app.his_adapter.event_bus import his_event_bus
from app.models.encounter import Encounter
from app.models.patient import Patient
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/his/queue",
    tags=["HIS对接"],
    dependencies=[Depends(require_his_enabled)],
)

# SSE 心跳间隔（秒）：队列空闲时发注释行保活，防 nginx/浏览器判定连接死亡
SSE_HEARTBEAT_SECONDS = 25


@router.get("/today")
async def today_queue(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """今日 HIS 接诊队列（当前医生）：进行中在前、按接诊时间倒序。

    只含 HIS 推送来源的接诊（his_external_ref 非空），医生手动新建的不混入。
    """
    # 时间窗不能按 date.today() 硬切（2026-08-14 第六轮审计修复）：
    # 原先只取今天零点之后的接诊，**跨零点仍在进行中的病人会从队列里凭空消失**
    # ——急诊夜班、住院跨天必然踩到，医生看不到还没看完的病人。
    # 改为：进行中的接诊不受时间窗限制一律保留，已完成的才按当天过滤
    # （避免把历史全量拉出来）。
    today_start = datetime.combine(date.today(), time.min)
    result = await db.execute(
        select(Encounter, Patient)
        .join(Patient, Encounter.patient_id == Patient.id)
        .where(
            Encounter.doctor_id == current_user.id,
            Encounter.his_external_ref.isnot(None),
            Encounter.status != "cancelled",
            or_(
                Encounter.status == "in_progress",
                Encounter.visited_at >= today_start,
            ),
        )
        .order_by(Encounter.visited_at.desc())
    )
    items = []
    for enc, patient in result.all():
        his_ref = enc.his_external_ref or {}
        items.append({
            "encounter_id": enc.id,
            "visit_no": enc.visit_no,
            "patient_id": patient.id,
            "patient_name": patient.name,
            "gender": patient.gender,
            "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
            "dept_name": his_ref.get("dept_name"),
            "status": enc.status,  # in_progress / completed
            "is_first_visit": enc.is_first_visit,
            "visited_at": enc.visited_at.isoformat() if enc.visited_at else None,
            # 回写状态（send_writeback 落进 his_external_ref.writeback）：
            # success / skipped / write_failed / refresh_failed / None(未触发)
            "writeback_status": (his_ref.get("writeback") or {}).get("status"),
        })
    return {"items": items}


async def _still_authorized(user_id: str, jti: str | None, iat: int | None) -> bool:
    """SSE 长连接的周期性重校验：账号仍激活、token 未被吊销、且未在本连接建立后改过密码。

    用独立会话查（请求会话在流式响应期间的生命周期不适合长期持有）。
    任何异常都判**通过**：这是保活路径，查库抖动不该把医生的叫号连接踢掉——
    真正的安全边界在每个业务请求的 get_current_user 上，这里是加固不是主防线。

    2026-08-17 第 15 轮审计修复：原实现只查 is_active / must_change_password，
    **漏了吊销与改密水印**——而这恰恰是本函数注释里声称要堵的两个场景。
    实测：建好 SSE 后登出（token 已进 revoked_tokens、普通请求已 401），这条
    长连接跨过 25 秒重校验点仍照发 ping 存活，继续把患者叫号 PHI 推给对面。
    「账号疑似泄露 → 登出/信息科重置密码」这套标准处置对已建立的 SSE 形同虚设。
    这里补齐两道，判定口径与 get_current_user 完全一致：
      · 吊销：jti 在黑名单（登出写入）→ 踢。复用 is_token_revoked（同一真源）。
      · 水印：token 的 iat 早于最后改密时刻 → 踢（医生自助改密后旧连接也要断）。
        时区口径同 get_current_user：iat（UTC 纪元秒）转 naive 本地再比 naive 的
        password_changed_at；老 token 无 iat 一并视为过期。
    """
    from datetime import datetime

    from app.database import AsyncSessionLocal
    from app.models.user import User as UserModel

    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(UserModel, user_id)
            if user is None or not user.is_active or user.must_change_password:
                return False
            # 吊销（登出）：与 get_current_user 同款检查，杀掉已吊销 token 的存量长连接
            if await is_token_revoked(db, jti):
                return False
            # 改密水印：签发早于最后改密时刻的 token 一并失效
            changed_at = getattr(user, "password_changed_at", None)
            if changed_at is not None:
                if iat is None or datetime.fromtimestamp(iat) < changed_at:
                    return False
            return True
    except Exception:
        logger.warning("his_queue.stream: 重校验查库失败，本轮放行 user_id=%s", user_id)
        return True


@router.post("/stream")
async def queue_stream(
    current_user: User = Depends(get_current_user),
    token: str = Depends(oauth2_scheme),
) -> StreamingResponse:
    """SSE 事件流：订阅本医生的事件频道，实时推送叫号与回写结果。

    用 POST 而非 GET：前端复用 streamSSE 工具（fetch + Authorization 头），
    绕开原生 EventSource 不能带鉴权头的限制。
    事件形状：
      {"type": "admit", ...}            新患者叫号（字段见 admit_service）
      {"type": "writeback_result", ...} 病历回写结果
    """
    channel = f"his:doctor:{current_user.id}"

    # 建连时取出本 token 的 jti / iat，交给心跳里的周期性重校验用（2026-08-17
    # 第 15 轮审计修复）。get_current_user 已验过签名有效期，这里只是把声明取出来，
    # 解析失败也不阻断建连（重校验拿不到 jti 就只退化到查账号状态，不比原来更差）。
    _jti: str | None = None
    _iat: int | None = None
    try:
        from jose import jwt

        from app.config import settings

        _claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        _jti = _claims.get("jti")
        _iat = _claims.get("iat")
    except Exception:
        logger.warning("his_queue.stream: 取 token 声明失败，重校验将只查账号状态")

    from app.his_adapter.event_bus import PUMP_DEAD_SENTINEL

    async def gen():
        # 先发一条连接确认，前端据此点亮"实时连接"状态
        yield 'data: {"type": "connected"}\n\n'
        async with his_event_bus.subscription(channel) as q:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # 借心跳做轻量重校验（2026-08-13 第五轮审计修复）：
                    # 本端点只在**建连时**鉴权一次，之后 while True 一直推下去——
                    # 医生账号被停用、密码被重置（账号疑似泄露的标准处置）、
                    # 甚至医生已登出，这条长连接照样把患者姓名/就诊信息推给对面。
                    # token 有效期 30 天，长连接可以挂一整天，等于鉴权形同虚设。
                    # 每 25 秒查一次库对 SSE 来说开销可忽略（每医生每 25 秒一次）。
                    if not await _still_authorized(current_user.id, _jti, _iat):
                        logger.info(
                            "his_queue.stream: 账号状态已变更，结束 SSE channel=%s", channel
                        )
                        return
                    yield ": ping\n\n"  # SSE 注释行，仅保活
                    continue
                # 泵死哨兵（2026-08-11 审计修复）：Redis 断连使泵退出、事件永久停投，
                # 若继续发心跳会造成"假活"连接、叫号/回写事件静默全丢。收到哨兵即结束
                # 本 SSE 流，让前端既有的断线重连 + 重拉今日队列逻辑接管，不丢病人。
                if event.get("type") == PUMP_DEAD_SENTINEL:
                    logger.warning("his_queue.stream: 事件泵终止，结束 SSE 流触发前端重连 channel=%s", channel)
                    return
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # 关键：让 nginx 不缓冲本响应，事件即时到达浏览器（免改 nginx 配置）
            "X-Accel-Buffering": "no",
        },
    )
