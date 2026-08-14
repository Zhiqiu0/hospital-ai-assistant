"""管理后台 token 用量统计服务（services/admin_stats_service.py）

从 api/v1/admin/stats.py 拆出（2026-08-11 超标文件拆分）：
DeepSeek 余额 / 阿里云连通性与余额 三个外部依赖查询 + 本地 ai_tasks 聚合，
路由层只做编排与响应。外部查询失败一律降级为 None/error 字段，不阻断后台首屏。
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.medical_record import AITask

logger = logging.getLogger(__name__)

# 病历时效达标阈值（小时，法定要求）。
# 门诊/急诊无强制法定时限（不纳入达标率，只统计中位耗时另议）。
#
# **起算点各不相同**（2026-08-14 第六轮审计修复）：原先所有类型统一用
# `submitted_at - visited_at`（入院时刻）算，而规范里——
#   · 入院记录 / 首次病程：从**入院**起算 ✓ 原实现正确
#   · 出院记录：从**出院**起算。住院半个月的病人用入院时刻算必然超时，
#     达标率被系统性压低，这个指标失去意义
#   · 手术记录：从**术后**起算。而系统里根本没有记录手术时刻的字段，
#     用任何现有时间点近似都是编数据——宁可不统计，也不给一个假指标。
_TIMELINESS_HOURS = {
    "admission_note": 24,        # 入院记录 24h（从入院起算）
    "first_course_record": 8,    # 首次病程 8h（从入院起算）
    "discharge_record": 24,      # 出院记录 24h（从**出院**起算）
}

# 起算点取自接诊的哪个字段：默认入院时刻（visited_at）
_TIMELINESS_START_FIELD = {
    "discharge_record": "completed_at",   # 出院时刻
}

# 暂不纳入达标率的类型及原因（写在这里而不是删掉，避免下次有人"顺手补回去"）
_TIMELINESS_EXCLUDED = {
    # 手术记录法定要求是"术后 24 小时内"，但系统未记录手术时刻。
    # 要纳入需先在住院模块增加手术时间字段，届时再加回 _TIMELINESS_HOURS。
    "op_record": "系统未记录手术时刻，无法确定起算点",
}


async def get_quality_health(db: AsyncSession, days: int = 30) -> dict:
    """病历质量与可靠性健康度（2026-08-11 病历质量闭环，评审/运营看板）。

    聚合四项数据真实支撑的指标（近 N 天）：
      - 回写成功率：HIS 来源已签发接诊按 writeback.status 分布（第一版 HIS 命门可观测）
      - 反馈采纳率：AI 建议 useful/useless（医生真实认可度）
      - 病历时效达标率：住院系病历 接诊→签发 是否在法定时限内
      - AI 采纳度：签发终稿 vs 最近一版 AI 草稿的编辑距离（2026-08-12 反馈闭环）
    注：AI 调用"成功率"不在此列——失败任务当前不落 ai_tasks，据此算会失真。
    """
    from app.models.ai_feedback import AISuggestionFeedback
    from app.models.encounter import Encounter
    from app.models.medical_record import MedicalRecord

    window_start = datetime.now() - timedelta(days=days)

    # ── 回写成功率（HIS 来源、近窗口、已有回写状态的接诊）──
    enc_rows = (await db.execute(
        select(Encounter.his_external_ref).where(
            Encounter.his_external_ref.isnot(None),
            Encounter.visited_at >= window_start,
        )
    )).scalars().all()
    wb_by_status: dict[str, int] = {}
    for ref in enc_rows:
        if (ref or {}).get("source") != "admit_push":
            continue
        wb = (ref or {}).get("writeback") or {}
        st = wb.get("status")
        if st is None:
            continue  # 尚未触发回写（未签发）不计入
        wb_by_status[st] = wb_by_status.get(st, 0) + 1
    wb_total = sum(wb_by_status.values())
    writeback = {
        "total": wb_total,
        "success": wb_by_status.get("success", 0),
        "success_rate": round(wb_by_status.get("success", 0) / wb_total, 3) if wb_total else None,
        "by_status": wb_by_status,
    }

    # ── AI 建议采纳率（近窗口 useful/useless 分类计）──
    fb_rows = (await db.execute(
        select(AISuggestionFeedback.suggestion_category, AISuggestionFeedback.verdict)
        .where(AISuggestionFeedback.recorded_at >= window_start)
    )).all()
    fb_useful = sum(1 for _, v in fb_rows if v == "useful")
    fb_total = len(fb_rows)
    by_cat: dict[str, dict] = {}
    for cat, v in fb_rows:
        c = by_cat.setdefault(cat, {"useful": 0, "total": 0})
        c["total"] += 1
        if v == "useful":
            c["useful"] += 1
    feedback = {
        "total": fb_total,
        "useful": fb_useful,
        "useful_rate": round(fb_useful / fb_total, 3) if fb_total else None,
        "by_category": by_cat,
    }

    # ── 病历时效达标率（住院系已签发病历 接诊→签发 时限）──
    rec_rows = (await db.execute(
        select(
            MedicalRecord.record_type,
            Encounter.visited_at,
            Encounter.completed_at,
            MedicalRecord.submitted_at,
        )
        .join(Encounter, MedicalRecord.encounter_id == Encounter.id)
        .where(
            MedicalRecord.status == "submitted",
            MedicalRecord.submitted_at.isnot(None),
            MedicalRecord.submitted_at >= window_start,
            MedicalRecord.record_type.in_(list(_TIMELINESS_HOURS.keys())),
        )
    )).all()
    tl: dict[str, dict] = {}
    for rtype, visited_at, completed_at, submitted_at in rec_rows:
        limit_h = _TIMELINESS_HOURS[rtype]
        t = tl.setdefault(rtype, {"total": 0, "on_time": 0, "limit_hours": limit_h})
        # 按类型取各自的起算点（出院记录用出院时刻，其余用入院时刻）
        start_at = (
            completed_at
            if _TIMELINESS_START_FIELD.get(rtype) == "completed_at"
            else visited_at
        )
        # 起算点缺失（如出院记录但接诊还没办出院）→ 不计入分母，
        # 否则会把"还没到该算的时候"误判成不达标
        if not start_at or not submitted_at:
            continue
        t["total"] += 1
        hours = (submitted_at - start_at).total_seconds() / 3600
        if hours <= limit_h:
            t["on_time"] += 1
    for r in tl.values():
        r["rate"] = round(r["on_time"] / r["total"], 3) if r["total"] else None

    # ── AI 采纳度（终稿 vs AI 草稿相似度，聚合逻辑在 _ai_adoption 模块）──
    from app.services._ai_adoption import adoption_stats
    ai_adoption = await adoption_stats(db, window_start)

    return {"window_days": days, "writeback": writeback, "feedback": feedback,
            "timeliness": tl, "ai_adoption": ai_adoption}


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
