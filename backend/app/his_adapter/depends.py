"""HIS 对接保险丝（depends.py）

提供 FastAPI 依赖 `require_his_enabled`，所有 /embed/* /desktop/* 路由
必须挂这个依赖。开关由 `settings.his_adapter_enabled` 控制：
  - True  → 放行
  - False → 直接抛 503 ServiceUnavailable，前端能感知"嵌入模式未启用"

为什么需要这层保险丝：
  嵌入模式与 SaaS 共用 service 层代码，万一嵌入模式触发了某个共用 service
  的 race condition 或边界 bug，可能波及 SaaS 用户。开关让运维 5 秒切回
  纯 SaaS 状态：改环境变量 + 重启后端 → 全院嵌入功能下线，SaaS 0 影响。

注意：保险丝只挡 HTTP 路由层，不挡内部代码 import。后端代码可以正常
import his_adapter 模块，只是开关关闭时 API 层会拒绝外部调用。
"""

from fastapi import HTTPException, status

from app.config import settings


async def require_his_enabled() -> None:
    """FastAPI 依赖：检查 HIS 对接全局开关。

    使用方式：
        @router.post("/embed/start", dependencies=[Depends(require_his_enabled)])
        async def start_embed(...): ...

    或者整个 router 注册时挂：
        app.include_router(
            embed_router,
            prefix="/api/v1/embed",
            dependencies=[Depends(require_his_enabled)],
        )

    Raises:
        HTTPException(503): 当 HIS_ADAPTER_ENABLED=false 时
    """
    if not settings.his_adapter_enabled:
        # 503 Service Unavailable 比 404 更准确——告诉客户端"功能在但被禁用"
        # 比"不存在"语义更清晰，前端能据此显示"嵌入模式当前关闭"而非"404"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "his_adapter_disabled",
                "message": "HIS 对接功能当前已关闭，请联系管理员开启 HIS_ADAPTER_ENABLED",
            },
        )
