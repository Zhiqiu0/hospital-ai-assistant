"""HIS 对接外部接口（接诊推送接收 + 病历回写触发），受保险丝保护。"""
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import get_current_user
from app.database import get_db
from app.his_adapter.depends import require_his_enabled
from app.his_adapter.models import AdmitPushRequest, ApiEnvelope, err, ok
from app.his_adapter.signing import timestamp_fresh, verify_sign
from app.models.user import User

router = APIRouter(
    prefix="/his",
    tags=["HIS对接"],
    dependencies=[Depends(require_his_enabled)],  # 全局保险丝
)


@router.post("/encounter/admit", response_model=ApiEnvelope)
async def admit_push(request: Request) -> ApiEnvelope:
    """接诊推送接收（HIS→我方，方案 A HTTP 通道）：验签 + 业务落地 + ACK。

    业务落地与 WS 通道共用 admit_service.handle_admit：
    患者自动建档 + 按工号派医生 + visit_id 幂等建接诊 + 发工作台叫号事件。
    """
    # 非 UTF-8 body 走信封而不是裸 500（2026-08-29 第五轮 HIS 契约审计）：
    # 国产 HIS（Delphi/老 Java 栈）默认 GBK 编码是现实形态，原先在一切校验
    # 之前 decode 抛 UnicodeDecodeError → 全局兜底 500，违背"HTTP 恒 200
    # 靠 code 区分"的信封契约（WS 通道早已容错，此处是遗漏）。
    try:
        body_raw = (await request.body()).decode("utf-8")
    except UnicodeDecodeError:
        return err(40004, "请求体必须为 UTF-8 编码")
    app_id = request.headers.get("X-App-Id", "")
    timestamp = request.headers.get("X-Timestamp", "")
    nonce = request.headers.get("X-Nonce", "")
    sign = request.headers.get("X-Sign", "")

    if not timestamp_fresh(timestamp, settings.his_sign_clock_skew_seconds):
        return err(40002, "时间戳过期或非法")
    if not app_id or app_id != settings.his_inbound_app_id:
        return err(40003, "appId 无效")
    if not verify_sign(app_id, timestamp, nonce, body_raw, sign, settings.his_inbound_app_secret):
        return err(40001, "签名校验失败")
    # 防重放：签名通过后，用一次性 nonce 拦截时间窗内的重放请求。
    # TTL 取时间戳偏差窗口 + 60s 缓冲；超窗后 timestamp_fresh 已会拒，nonce 无需再记。
    from app.services.redis_cache import redis_cache
    if not await redis_cache.claim_nonce(
        "his_admit", nonce, ttl=settings.his_sign_clock_skew_seconds + 60
    ):
        return err(40006, "nonce 重复（疑似重放）")
    try:
        payload = AdmitPushRequest.model_validate_json(body_raw)
    except ValidationError:
        return err(40004, "参数缺失或格式错误")

    from app.his_adapter import admit_service
    try:
        result = await admit_service.handle_admit(payload)
    except admit_service.AdmitError as exc:
        return err(exc.code, exc.message)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "his_admit.http_error: visit_id=%s", payload.visit_id)
        return err(50000, "服务内部错误")
    return ok({"visit_id": payload.visit_id, "encounter_id": result.encounter_id})


@router.post("/encounter/{encounter_id}/writeback", response_model=ApiEnvelope)
async def trigger_writeback(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ApiEnvelope:
    """医生在工作台手动触发/重试病历回写（我方→HIS：写入 + 刷新）。

    走与签发钩子相同的派发链路（2026-08-13 复检修复）：生产 2 worker，厂商 WS
    长连接只挂在其中一个进程，本端点原先就地执行 send_writeback，请求落到没有
    连接的 worker 时会误判「WS 未连接」→ 返回 skipped 并把队列上的回写状态覆写
    成未回写，医生反复点击结果随机。改走 dispatch_writeback 后由持有连接的
    worker 抢占执行，结果经 SSE（writeback_result）推回工作台。
    """
    # 归属校验（2026-08-11 审计修复）：只能回写自己的接诊，防越权回写他人病历。
    # 管理员天然放行。
    from app.core.authz import assert_encounter_access
    enc = await assert_encounter_access(db, encounter_id, current_user)
    if not (enc.his_external_ref or {}).get("source"):
        return err(40005, "该接诊不是 HIS 来源，无需回写")

    from app.his_adapter.bg_tasks import spawn
    from app.his_adapter.writeback_dispatch import dispatch_writeback

    # 逐文书补推（2026-08-29 粒度下沉）：住院一次接诊多份文书各有回写状态，
    # 手动重试应把「未成功的那些」都补上，而不是只推 builder 挑的最新一份。
    # 全部成功时重推最新一份（医生手动点=明确要重推，幂等覆盖无害）。
    from sqlalchemy import select as sa_select
    from app.models.medical_record import MedicalRecord
    recs = (await db.execute(
        sa_select(MedicalRecord).where(
            MedicalRecord.encounter_id == encounter_id,
            MedicalRecord.status == "submitted",
        ).order_by(MedicalRecord.submitted_at.desc())
    )).scalars().all()
    wbr = (enc.his_external_ref or {}).get("writeback_records") or {}
    pending = [
        r for r in recs
        if (wbr.get(f"{r.record_type}:{r.record_no if r.record_no is not None else '0'}")
            or {}).get("status") != "success"
    ]
    targets = pending or recs[:1]
    if targets:
        for r in targets:
            spawn(dispatch_writeback(encounter_id, current_user.id,
                                     enc.visit_no or "", record_id=r.id),
                  name=f"writeback:manual:{encounter_id}:{r.id}")
    else:
        # 无已签发文书：保留旧行为兜底（builder 自行择取，通常返回 skipped）
        spawn(dispatch_writeback(encounter_id, current_user.id, enc.visit_no or ""),
              name=f"writeback:manual:{encounter_id}")
    n = max(len(targets), 1)
    return ok({"status": "dispatched", "count": n,
               "message": f"已发起 {n} 份文书回写，结果稍后推送"})
