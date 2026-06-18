"""HIS 对接外部接口（接诊推送接收等），HMAC 签名鉴权，受保险丝保护。"""
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.config import settings
from app.his_adapter.depends import require_his_enabled
from app.his_adapter.models import AdmitPushRequest, ApiEnvelope, err, ok
from app.his_adapter.signing import timestamp_fresh, verify_sign

router = APIRouter(
    prefix="/his",
    tags=["HIS对接"],
    dependencies=[Depends(require_his_enabled)],  # 全局保险丝
)


@router.post("/encounter/admit", response_model=ApiEnvelope)
async def admit_push(request: Request) -> ApiEnvelope:
    """接诊推送接收（HIS→我方）：验签 + 校验载荷 + ACK。

    注：本期仅建立签名通道并校验载荷；患者/接诊的建立仍由 /embed/start 负责
    （接诊推送与 embed/start 的联动属待定设计）。
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
    try:
        payload = AdmitPushRequest.model_validate_json(body_raw)
    except ValidationError:
        return err(40004, "参数缺失或格式错误")

    # 本期：仅确认收到（回声 visit_id）。后续按设计补患者/接诊联动。
    return ok({"visit_id": payload.visit_id})
