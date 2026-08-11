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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
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
    today_start = datetime.combine(date.today(), time.min)
    result = await db.execute(
        select(Encounter, Patient)
        .join(Patient, Encounter.patient_id == Patient.id)
        .where(
            Encounter.doctor_id == current_user.id,
            Encounter.his_external_ref.isnot(None),
            Encounter.visited_at >= today_start,
            Encounter.status != "cancelled",
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
        })
    return {"items": items}


@router.post("/stream")
async def queue_stream(
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE 事件流：订阅本医生的事件频道，实时推送叫号与回写结果。

    用 POST 而非 GET：前端复用 streamSSE 工具（fetch + Authorization 头），
    绕开原生 EventSource 不能带鉴权头的限制。
    事件形状：
      {"type": "admit", ...}            新患者叫号（字段见 admit_service）
      {"type": "writeback_result", ...} 病历回写结果
    """
    channel = f"his:doctor:{current_user.id}"

    async def gen():
        # 先发一条连接确认，前端据此点亮"实时连接"状态
        yield 'data: {"type": "connected"}\n\n'
        async with his_event_bus.subscription(channel) as q:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # SSE 注释行，仅保活
                    continue
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
