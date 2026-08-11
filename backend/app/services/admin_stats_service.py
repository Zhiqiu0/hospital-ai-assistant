"""管理后台 token 用量统计服务（services/admin_stats_service.py）

从 api/v1/admin/stats.py 拆出（2026-08-11 超标文件拆分）：
DeepSeek 余额 / 阿里云连通性与余额 三个外部依赖查询 + 本地 ai_tasks 聚合，
路由层只做编排与响应。外部查询失败一律降级为 None/error 字段，不阻断后台首屏。
"""
import asyncio
import logging
from datetime import date

import httpx
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.medical_record import AITask

logger = logging.getLogger(__name__)


async def get_deepseek_balance() -> dict | None:
    """DeepSeek 官方余额查询；失败返回 None（外部依赖问题只记 warning）。"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            )
            if resp.status_code == 200:
                infos = resp.json().get("balance_infos", [])
                if infos:
                    return infos[0]
    except Exception as exc:
        # 余额查询挂了不阻断后台首屏，但要写日志（之前 pass 导致 0 线索）
        logger.warning("admin.deepseek_balance: failed err=%s", exc)
    return None


async def get_aliyun_status() -> dict:
    """阿里云：模型连通性探测（1 token 调用）+ AccessKey 账户余额查询。"""
    status: dict = {"connected": False, "model": settings.aliyun_model,
                    "error": None, "balance": None}
    if settings.aliyun_api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{settings.aliyun_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.aliyun_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.aliyun_model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                    },
                )
                if resp.status_code == 200:
                    status["connected"] = True
                else:
                    status["error"] = f"HTTP {resp.status_code}"
        except Exception as exc:
            # 错误透传给前端展示外，同时写日志（之前只透传 → Sentry 看不到聚合）
            status["error"] = str(exc)
            logger.warning("admin.aliyun_check: failed err=%s", exc)
    else:
        status["error"] = "未配置 ALIYUN_API_KEY"

    # 阿里云账户余额（需要 AccessKey；SDK 是同步实现，丢线程池防阻塞事件循环）
    if settings.alibaba_access_key_id and settings.alibaba_access_key_secret:
        try:
            from alibabacloud_bssopenapi20171214 import client as bss_client
            from alibabacloud_tea_openapi import models as open_api_models
            bss_config = open_api_models.Config(
                access_key_id=settings.alibaba_access_key_id,
                access_key_secret=settings.alibaba_access_key_secret,
                endpoint="business.aliyuncs.com",
            )
            bss = bss_client.Client(bss_config)
            bal_resp = await asyncio.get_event_loop().run_in_executor(
                None, bss.query_account_balance
            )
            d = bal_resp.body.data
            status["balance"] = {
                "available_amount": d.available_amount,
                "available_cash_amount": d.available_cash_amount,
                "credit_amount": d.credit_amount,
                "currency": d.currency,
            }
        except Exception as exc:
            status["balance_error"] = str(exc)
            logger.warning("admin.aliyun_balance: failed err=%s", exc)
    return status


async def get_token_usage_totals(db: AsyncSession) -> dict:
    """本地 ai_tasks 表的 token 消耗聚合（总量 / 今日 / 按任务类型）。"""
    total_input = await db.execute(select(func.coalesce(func.sum(AITask.token_input), 0)))
    total_output = await db.execute(select(func.coalesce(func.sum(AITask.token_output), 0)))
    total_calls = await db.execute(select(func.count()).select_from(AITask))

    today = date.today()
    today_input = await db.execute(
        select(func.coalesce(func.sum(AITask.token_input), 0)).where(
            cast(AITask.created_at, Date) == today
        )
    )
    today_output = await db.execute(
        select(func.coalesce(func.sum(AITask.token_output), 0)).where(
            cast(AITask.created_at, Date) == today
        )
    )

    type_stats_result = await db.execute(
        select(
            AITask.task_type,
            func.count().label("calls"),
            func.coalesce(func.sum(AITask.token_input), 0).label("input_tokens"),
            func.coalesce(func.sum(AITask.token_output), 0).label("output_tokens"),
        ).group_by(AITask.task_type)
    )
    type_stats = [
        {
            "task_type": row.task_type,
            "calls": row.calls,
            "input_tokens": row.input_tokens,
            "output_tokens": row.output_tokens,
        }
        for row in type_stats_result
    ]

    return {
        "total_input_tokens": total_input.scalar(),
        "total_output_tokens": total_output.scalar(),
        "total_calls": total_calls.scalar(),
        "today_input_tokens": today_input.scalar(),
        "today_output_tokens": today_output.scalar(),
        "by_task_type": type_stats,
    }
