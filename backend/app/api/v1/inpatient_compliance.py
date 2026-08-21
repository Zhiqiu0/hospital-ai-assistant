"""
住院时效合规子路由（GET /api/v1/encounters/{id}/compliance）

从 inpatient.py 拆出（Round 5 瘦身）：负责住院文书书写时限的合规检查。
行为与拆分前逐字一致，路由路径/方法/依赖零改动。本模块自建 router，
由 inpatient.py 主 router 拼回。
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.core.authz import assert_encounter_access
from app.database import get_db
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord

router = APIRouter()


# 时限规则收口到唯一真相源（2026-08-21 阶段0）：此前本表与后台统计
# admin_stats_service 各写一份，已经漂移（后台有出院记录 24h、这里没有）
from app.services.record_deadlines import RECORD_DEADLINES as _COMPLIANCE_RULES  # noqa: E402


@router.get("/encounters/{encounter_id}/compliance")
async def get_compliance(
    encounter_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """检查住院文书时效合规情况。

    返回各类必须文书的完成状态与剩余时间。
    """
    await assert_encounter_access(db, encounter_id, current_user)
    # 获取接诊信息（入院时间）
    enc_result = await db.execute(
        select(Encounter).where(Encounter.id == encounter_id)
    )
    enc = enc_result.scalars().first()
    if not enc:
        raise HTTPException(status_code=404, detail="接诊不存在")

    now = datetime.now()

    # 查询该接诊**已签发**的文书及其签发时刻
    #
    # 两处都是 2026-08-14 第六轮审计修复：
    #   ① 原先不过滤 status——AI 一生成就建了 MedicalRecord 行，**空白草稿也被
    #      算作"已完成"**：医生什么都没写，合规面板却显示"入院记录已完成"，
    #      而这个面板正是给医生和质控看"还有哪些文书没写"的。
    #   ② 原先取 created_at（草稿**建立**时刻）当完成时间，用它判超时等于
    #      把"什么时候开始写"当成"什么时候写完"——只要 AI 早早生成过草稿，
    #      哪怕拖到几天后才签发，也会被判成"按时完成"。
    # 时效合规的口径必须是"文书签发了没有、什么时候签的"。
    rec_result = await db.execute(
        select(MedicalRecord.record_type, MedicalRecord.submitted_at)
        .where(
            MedicalRecord.encounter_id == encounter_id,
            MedicalRecord.status == "submitted",
            MedicalRecord.submitted_at.isnot(None),
        )
        .order_by(MedicalRecord.submitted_at.asc())
    )
    existing: dict[str, datetime] = {}
    for row in rec_result.all():
        # 同类型多份（住院病程）取最早那份的签发时刻——时效考核的是"首次完成"
        if row.record_type not in existing:
            existing[row.record_type] = row.submitted_at

    items = []
    for rule in _COMPLIANCE_RULES:
        # 起算点按类型区分（2026-08-21 阶段0）：入院记录/首程从入院（visited_at）
        # 起算，出院记录从出院（completed_at）起算。出院时刻为 NULL（还没办出院）
        # 时该文书整条不显示——绝不能拿 now() 兜底，那会让住院中的病人从挂上
        # 规则那一刻就"永久超时"（admin_stats 第六轮审计修过同一个坑）
        start_time = getattr(enc, rule["start_field"], None)
        if start_time is None:
            if rule["start_field"] == "visited_at":
                # 入院时刻理论上必有；缺失时保守用当前时刻起算（维持原兜底）
                start_time = now
            else:
                continue
        deadline = start_time + timedelta(hours=rule["deadline_hours"])
        done_at = existing.get(rule["record_type"])
        remaining_seconds = (deadline - now).total_seconds()

        if done_at:
            status = "done"
            delay_minutes = (done_at - deadline).total_seconds() / 60
            detail = f"已完成（{'超时' if delay_minutes > 0 else '按时'}）"
        elif remaining_seconds < 0:
            status = "overdue"
            overdue_hours = abs(remaining_seconds) / 3600
            detail = f"已超时 {overdue_hours:.1f} 小时"
        elif remaining_seconds < 3600:
            status = "urgent"
            detail = f"剩余 {remaining_seconds/60:.0f} 分钟"
        else:
            status = "ok"
            detail = f"剩余 {remaining_seconds/3600:.1f} 小时"

        items.append({
            "record_type": rule["record_type"],
            "label": rule["label"],
            "deadline_hours": rule["deadline_hours"],
            "deadline": deadline.isoformat(),
            "status": status,   # done / ok / urgent / overdue
            "detail": detail,
            "done_at": done_at.isoformat() if done_at else None,
        })

    return {
        "encounter_id": encounter_id,
        "admission_time": (enc.visited_at or now).isoformat(),
        "items": items,
    }
