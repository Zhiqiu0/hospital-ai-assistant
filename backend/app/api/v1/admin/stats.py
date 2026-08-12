"""
管理后台统计接口（/api/v1/admin/stats/*）

提供运营概览、AI token 用量统计及阿里云账户余额查询。
"""

# ── 标准库 ────────────────────────────────────────────────────────────────────
import logging
from datetime import date, datetime, timedelta

# ── 第三方库 ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter, Depends
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.core.security import require_admin
from app.database import get_db
from app.models.encounter import Encounter
from app.models.medical_record import AITask, QCIssue
from app.models.user import Department
from app.services.admin_stats_service import (
    get_aliyun_status,
    get_deepseek_balance,
    get_quality_health,
    get_token_usage_totals,
)
from app.services.redis_cache import redis_cache

# 模块级 logger：admin 后台请求量低，异常都值得上 Sentry
logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), current_user=Depends(require_admin)):
    """运营概览：6 个全表聚合 count，admin 仪表盘首屏。

    Redis 缓存 30 秒；管理后台不会因为 30s 旧数据出问题（业务用户也看不到）。
    缓存命中时仪表盘秒开。
    """
    cache_key = "admin:stats:overview"
    cached = await redis_cache.get_json(cache_key)
    if cached is not None:
        return cached

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

    overview_data = {
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
    await redis_cache.set_json(cache_key, overview_data, ttl=30)
    return overview_data


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
        .where(Department.is_active.is_(True))
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
    """AI token 用量 + 双厂商余额（外部查询逻辑在 admin_stats_service）。"""
    balance_info = await get_deepseek_balance()
    aliyun_status = await get_aliyun_status()
    totals = await get_token_usage_totals(db)
    return {"balance": balance_info, "aliyun_status": aliyun_status, **totals}


@router.get("/quality-health")
async def quality_health(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """病历质量与可靠性健康度：回写成功率 + AI建议采纳率 + 病历时效达标率（近30天）。"""
    return await get_quality_health(db)
