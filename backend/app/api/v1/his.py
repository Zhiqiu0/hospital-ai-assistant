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
from app.his_adapter.writeback_sender import send_writeback
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
    body_raw = (await request.body()).decode("utf-8")
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
    """医生在工作台确认后触发病历回写（我方→HIS：写入 + 刷新）。

    回写地址未配置时返回 skipped（联调前安全空跑）。
    """
    # 归属校验（2026-08-11 审计修复）：只能回写自己的接诊，防越权回写他人病历。
    # 管理员天然放行；embed 票被限制在其绑定接诊内，正是本端点的预期语义。
    from app.core.authz import assert_encounter_access
    await assert_encounter_access(db, encounter_id, current_user)
    try:
        result = await send_writeback(db, encounter_id)
    except ValueError as exc:
        return err(40005, str(exc))
    if result.ok:
        return ok({"status": "success", "his_doc_id": result.his_doc_id})
    if result.status == "skipped":
        return ok({"status": "skipped", "message": result.message})
    return err(50001, f"回写失败({result.status})：{result.message}")
