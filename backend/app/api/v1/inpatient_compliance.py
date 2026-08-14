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


# 各类住院文书的书写时限规范（小时）
_COMPLIANCE_RULES = [
    {
        "record_type": "admission_note",
        "label": "入院记录",
        "deadline_hours": 24,
        "required": True,
    },
    {
        "record_type": "first_course_record",
        "label": "首次病程记录",
        "deadline_hours": 8,
        "required": True,
    },
]


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

    admission_time = enc.visited_at or datetime.now()
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
        deadline = admission_time + timedelta(hours=rule["deadline_hours"])
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
        "admission_time": admission_time.isoformat(),
        "items": items,
    }
