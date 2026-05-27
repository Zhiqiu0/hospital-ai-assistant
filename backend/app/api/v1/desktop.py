"""桌面 Agent 配套 API

路由前缀：/api/v1/desktop
所有路由由 his_adapter.depends.require_his_enabled 守门。

桌面 Agent（医生电脑上的常驻 exe）通过这些接口：
  - 拉字段映射 YAML（按医院适配 HIS）
  - 上报心跳（运维监控 Agent 在线情况）
  - 上报填入审计日志（合规追溯）
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.database import get_db
from app.his_adapter import config_loader
from app.his_adapter.depends import require_his_enabled
from app.his_adapter.models import DesktopHeartbeat, FillResult
from app.models.user import User

router = APIRouter(
    prefix="/desktop",
    tags=["desktop_agent"],
    dependencies=[Depends(require_his_enabled)],
)

logger = logging.getLogger("app.his_adapter.desktop")


@router.get("/config")
async def get_field_map(
    hospital_code: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    """桌面 Agent 启动时拉自己医院对应的字段映射 YAML。

    路由 GET，无写副作用。Agent 缓存到本地，每天检查一次更新。
    """
    mapping = config_loader.get_map(hospital_code)
    if not mapping:
        # 不抛 404 直接返回空，Agent 走 fallback（用上次缓存的）
        return {"hospital_code": hospital_code, "mapping": None}
    return {"hospital_code": hospital_code, "mapping": mapping}


@router.get("/supported-hospitals")
async def list_hospitals(current_user: User = Depends(get_current_user)) -> dict:
    """列出所有已配置字段映射的医院。"""
    return {"items": config_loader.list_supported_hospitals()}


@router.post("/heartbeat")
async def report_heartbeat(
    hb: DesktopHeartbeat,
    current_user: User = Depends(get_current_user),
) -> dict:
    """桌面 Agent 心跳上报（每 5 分钟一次）。

    MVP 阶段先只打日志，二期再加 agent_status 表 + 监控告警。
    """
    logger.info(
        "agent.heartbeat: device_id=%s version=%s his_brand=%s his_detected=%s",
        hb.agent_device_id,
        hb.agent_version,
        hb.his_brand,
        hb.his_detected,
    )
    return {"ok": True}


@router.post("/audit")
async def report_audit(
    result: FillResult,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """填入操作审计上报。

    桌面 Agent 完成 fill 后调本接口，把每个字段的填入结果写审计日志。
    MVP 阶段先用结构化日志（Sentry / ELK 可索引），二期再考虑专表存储。
    """
    logger.info(
        "agent.fill_audit: encounter=%s status=%s succeeded=%d/%d duration_ms=%d",
        result.encounter_id,
        result.status,
        result.succeeded,
        result.total_fields,
        result.duration_ms,
    )
    # 失败字段额外打 WARNING 方便排查
    for fr in result.field_results:
        if fr.status != "success":
            logger.warning(
                "agent.fill_field_failed: field=%s status=%s error=%s",
                fr.field_key,
                fr.status,
                fr.error_message,
            )
    return {"ok": True, "recorded": result.total_fields}
