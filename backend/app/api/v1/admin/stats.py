from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Date
from app.database import get_db
from app.core.security import require_admin
from app.models.encounter import Encounter
from app.models.medical_record import AITask, QCIssue
from app.models.user import Department, User
from app.config import settings
from datetime import date, datetime, timedelta
import httpx

router = APIRouter()


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), current_user=Depends(require_admin)):
    today = date.today()

    # Total / today encounters
    total_encounters = (await db.execute(select(func.count()).select_from(Encounter))).scalar() or 0
    today_encounters = (await db.execute(
        select(func.count()).select_from(Encounter).where(func.date(Encounter.visited_at) == today)
    )).scalar() or 0

    # AI task totals
    total_ai_tasks = (await db.execute(select(func.count()).select_from(AITask))).scalar() or 0

    # Per-type counts
    type_counts_result = await db.execute(
        select(AITask.task_type, func.count().label("cnt")).group_by(AITask.task_type)
    )
    type_counts: dict[str, int] = {row.task_type: row.cnt for row in type_counts_result}

    # QC issues totals and breakdown
    total_qc_issues = (await db.execute(select(func.count()).select_from(QCIssue))).scalar() or 0
    issue_type_result = await db.execute(
        select(QCIssue.issue_type, func.count().label("cnt")).group_by(QCIssue.issue_type)
    )
    issue_counts: dict[str, int] = {row.issue_type: row.cnt for row in issue_type_result}

    risk_level_result = await db.execute(
        select(QCIssue.risk_level, func.count().label("cnt")).group_by(QCIssue.risk_level)
    )
    risk_counts: dict[str, int] = {row.risk_level: row.cnt for row in risk_level_result}

    return {
        "today_encounters": today_encounters,
        "total_encounters": total_encounters,
        "total_ai_tasks": total_ai_tasks,
        "total_qc_issues": total_qc_issues,
        # per-feature counts
        "generate_count": type_counts.get("generate", 0),
        "polish_count": type_counts.get("polish", 0),
        "qc_count": type_counts.get("qc", 0),
        "inquiry_count": type_counts.get("inquiry", 0),
        "exam_count": type_counts.get("exam", 0),
        # QC issue type breakdown
        "completeness_issues": issue_counts.get("completeness", 0),
        "format_issues": issue_counts.get("format", 0),
        "logic_issues": issue_counts.get("logic", 0),
        # risk level breakdown
        "high_risk_issues": risk_counts.get("high", 0),
        "medium_risk_issues": risk_counts.get("medium", 0),
        "low_risk_issues": risk_counts.get("low", 0),
    }


@router.get("/usage")
async def usage_stats(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """按科室统计接诊次数和AI调用次数"""
    dept_result = await db.execute(
        select(
            Department.id,
            Department.name,
            func.count(Encounter.id).label("encounter_count"),
        )
        .outerjoin(Encounter, Encounter.department_id == Department.id)
        .where(Department.is_active == True)
        .group_by(Department.id, Department.name)
        .order_by(func.count(Encounter.id).desc())
    )
    items = [
        {"department_id": row.id, "department_name": row.name, "encounter_count": row.encounter_count}
        for row in dept_result
    ]

    # 近7日每日接诊趋势
    seven_days_ago = datetime.now() - timedelta(days=7)
    day_col = cast(Encounter.visited_at, Date)
    daily_result = await db.execute(
        select(day_col.label("day"), func.count().label("cnt"))
        .where(Encounter.visited_at >= seven_days_ago)
        .group_by(day_col)
        .order_by(day_col)
    )
    daily = [{"date": str(row.day), "count": row.cnt} for row in daily_result]

    return {"by_department": items, "daily_trend": daily}


@router.get("/qc-issues")
async def qc_issue_stats(db: AsyncSession = Depends(get_db), current_user=Depends(require_admin)):
    """质控问题按类型和风险等级统计"""
    type_result = await db.execute(
        select(QCIssue.issue_type, QCIssue.risk_level, func.count().label("cnt"))
        .group_by(QCIssue.issue_type, QCIssue.risk_level)
        .order_by(func.count().desc())
    )
    items = [
        {"issue_type": row.issue_type, "risk_level": row.risk_level, "count": row.cnt}
        for row in type_result
    ]

    # top fields with most issues
    field_result = await db.execute(
        select(QCIssue.field_name, func.count().label("cnt"))
        .where(QCIssue.field_name.isnot(None))
        .group_by(QCIssue.field_name)
        .order_by(func.count().desc())
        .limit(10)
    )
    top_fields = [{"field_name": row.field_name, "count": row.cnt} for row in field_result]

    return {"by_type": items, "top_fields": top_fields}


@router.get("/token-usage")
async def token_usage(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    # 1. 从 DeepSeek 官方 API 获取实时余额
    balance_info = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                infos = data.get("balance_infos", [])
                if infos:
                    balance_info = infos[0]
    except Exception:
        pass

    # 1b. 阿里云：连接检测 + AccessKey 余额查询
    aliyun_status = {"connected": False, "model": settings.aliyun_model, "error": None, "balance": None}
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
                    aliyun_status["connected"] = True
                else:
                    aliyun_status["error"] = f"HTTP {resp.status_code}"
        except Exception as e:
            aliyun_status["error"] = str(e)
    else:
        aliyun_status["error"] = "未配置 ALIYUN_API_KEY"

    # 阿里云账户余额（需要 AccessKey）
    if settings.alibaba_access_key_id and settings.alibaba_access_key_secret:
        try:
            import asyncio
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
            aliyun_status["balance"] = {
                "available_amount": d.available_amount,
                "available_cash_amount": d.available_cash_amount,
                "credit_amount": d.credit_amount,
                "currency": d.currency,
            }
        except Exception as e:
            aliyun_status["balance_error"] = str(e)

    # 2. 从本地 ai_tasks 表统计 token 消耗
    total_input = await db.execute(select(func.coalesce(func.sum(AITask.token_input), 0)))
    total_output = await db.execute(select(func.coalesce(func.sum(AITask.token_output), 0)))
    total_calls = await db.execute(select(func.count()).select_from(AITask))

    # 今日消耗
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

    # 按任务类型统计
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
        "balance": balance_info,
        "aliyun_status": aliyun_status,
        "total_input_tokens": total_input.scalar(),
        "total_output_tokens": total_output.scalar(),
        "total_calls": total_calls.scalar(),
        "today_input_tokens": today_input.scalar(),
        "today_output_tokens": today_output.scalar(),
        "by_task_type": type_stats,
    }
