# -*- coding: utf-8 -*-
"""质控指标统计（api/v1/qc/stats.py，2026-08-21 阶段5）

  GET /qc/stats/summary?days=30      指标汇总（月度通报数据源）
  GET /qc/stats/export?days=30       CSV 导出（医务科《病案首页质量通报》素材）

指标口径（每处都按"可被数据真实支撑"设计，绝不给假指标）：
  - 评分类：qc_reports 按 (encounter, record_type) 取**最新一次**（同一文书
    医生反复点质控只算最后状态，否则测的是"谁爱点按钮"）；
  - 缺陷条款 Top：最新报告的法定扣分明细（rule_code）计数；
  - 复核类：qc_reviews 通过/退回计数 + 当前待复核数；
  - 归档代理口径：本系统只能管到"签发"（归档动作在 HIS/病案室），指标 =
    出院后 7 个工作日内该接诊全部文书完成签发的占比，前端明示这一口径。
    工作日按 services/workdays.py（周末+法定节假日+调休）。
权限：随 /qc/* 路由树 require_qc_officer（质控员+管理员）。
"""
import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.security import get_current_user
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord, QCReport, QCReview
from app.models.user import Department
from app.services.workdays import add_workdays

router = APIRouter()


async def _collect_summary(db: AsyncSession, days: int) -> dict:
    """汇总近 N 天指标（summary 与 export 共用同一实现，杜绝两套口径）。"""
    since = datetime.now() - timedelta(days=days)

    # ── 评分：每 (encounter, record_type) 最新一次 ──────────────────
    # 用 group-by max(created_at) 再 join 的通用写法（PG 的 DISTINCT ON 在
    # 测试用 SQLite 下会退化为全行去重，口径悄悄失真——踩过当场改掉）
    latest_at = (
        select(
            QCReport.encounter_id.label("enc"),
            QCReport.record_type.label("rt"),
            func.max(QCReport.created_at).label("mx"),
        )
        .where(QCReport.created_at >= since)
        .group_by(QCReport.encounter_id, QCReport.record_type)
        .subquery()
    )
    rows = (await db.execute(
        select(QCReport).join(
            latest_at,
            (QCReport.encounter_id == latest_at.c.enc)
            & (QCReport.record_type == latest_at.c.rt)
            & (QCReport.created_at == latest_at.c.mx),
        )
    )).scalars().all()

    dept_names = {
        d.id: d.name for d in (await db.execute(select(Department))).scalars().all()
    }

    by_dept: dict[str, dict] = {}
    rule_counter: dict[str, dict] = {}
    for r in rows:
        key = r.department_id or "__none__"
        bucket = by_dept.setdefault(key, {
            "department": dept_names.get(r.department_id, "未挂科室"),
            "count": 0, "score_sum": 0.0, "grade_a": 0, "passed": 0,
        })
        bucket["count"] += 1
        bucket["score_sum"] += float(r.score or 0)
        if r.grade == "甲级":
            bucket["grade_a"] += 1
        if r.passed:
            bucket["passed"] += 1
        for d in (r.deductions or []):
            code = d.get("rule_code")
            if not code:
                continue
            rc = rule_counter.setdefault(code, {"rule_code": code, "count": 0,
                                                "description": d.get("description", "")})
            rc["count"] += 1

    dept_stats = sorted(
        (
            {
                "department": b["department"],
                "count": b["count"],
                "avg_score": round(b["score_sum"] / b["count"], 1) if b["count"] else 0,
                "grade_a_rate": round(b["grade_a"] / b["count"] * 100, 1) if b["count"] else 0,
                "pass_rate": round(b["passed"] / b["count"] * 100, 1) if b["count"] else 0,
            }
            for b in by_dept.values()
        ),
        key=lambda x: -x["count"],
    )
    top_rules = sorted(rule_counter.values(), key=lambda x: -x["count"])[:10]

    # ── 复核 ─────────────────────────────────────────────────────────
    review_rows = (await db.execute(
        select(QCReview.conclusion, func.count())
        .where(QCReview.created_at >= since)
        .group_by(QCReview.conclusion)
    )).all()
    reviews = {c: n for c, n in review_rows}

    # ── 归档代理口径：出院后 7 个工作日内全部文书签发完成率 ──────────
    discharged = (await db.execute(
        select(Encounter)
        .where(
            Encounter.visit_type == "inpatient",
            Encounter.completed_at.isnot(None),
            Encounter.completed_at >= since,
        )
    )).scalars().all()
    # 一次取回全部出院接诊的文书再按接诊分桶（2026-08-28 体检修复）：
    # 原写法在循环内逐接诊查询（N+1），按年看板/导出时是数千次串行查询，
    # 2 核生产机上单次请求拖到秒级；summary 与 export 各算一遍则翻倍。
    recs_by_enc: dict[str, list] = {}
    if discharged:
        rec_rows = (await db.execute(
            select(MedicalRecord.encounter_id, MedicalRecord.status,
                   MedicalRecord.submitted_at)
            .where(MedicalRecord.encounter_id.in_([e.id for e in discharged]))
        )).all()
        for eid, s, t in rec_rows:
            recs_by_enc.setdefault(eid, []).append((s, t))
    archive_total = archive_ok = 0
    now = datetime.now()
    for enc in discharged:
        deadline = add_workdays(enc.completed_at, 7)
        recs = recs_by_enc.get(enc.id, [])
        if not recs:
            continue
        archive_total += 1
        all_signed = all(s == "submitted" and t is not None for s, t in recs)
        latest_sign = max((t for _, t in recs if t), default=None)
        if all_signed and latest_sign and latest_sign <= deadline:
            archive_ok += 1
        elif not all_signed and now <= deadline:
            # 时限未到且还有草稿——不计入分母（既不达标也不违约，避免误伤在途）
            archive_total -= 1

    return {
        "days": days,
        "dept_stats": dept_stats,
        "top_rules": top_rules,
        "reviews": {
            "passed": reviews.get("passed", 0),
            "returned": reviews.get("returned", 0),
        },
        "archive_proxy": {
            "total": archive_total,
            "ok": archive_ok,
            "rate": round(archive_ok / archive_total * 100, 1) if archive_total else None,
            "caliber": "出院后7个工作日内全部文书签发完成（本系统管到签发；"
                        "归档动作在HIS/病案室，此为代理口径）",
        },
    }


@router.get("/stats/summary")
async def stats_summary(
    days: int = Query(30, ge=1, le=366),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """质控指标汇总（科室评分/缺陷条款 Top/复核/归档代理口径）。"""
    return await _collect_summary(db, days)


@router.get("/stats/export")
async def stats_export(
    days: int = Query(30, ge=1, le=366),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """CSV 导出（Excel 可直接打开，作医务科月度通报素材）。"""
    data = await _collect_summary(db, days)

    def _csv_safe(v):
        """CSV 公式注入防护（2026-08-28 极端字符审计）：科室名可由 HIS
        dept_name 自动建档带入，= + - @ 开头会被 Excel 当公式执行。
        危险首字符前置单引号（Excel 显示原文不执行）。"""
        s = str(v)
        return f"'{s}" if s[:1] in ("=", "+", "-", "@") else v

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"病历质控指标汇总（近 {days} 天，导出于 {datetime.now():%Y-%m-%d %H:%M}）"])
    w.writerow([])
    w.writerow(["科室", "评分文书数", "平均分", "甲级率%", "合格率%"])
    for d in data["dept_stats"]:
        w.writerow([_csv_safe(d["department"]), d["count"], d["avg_score"],
                    d["grade_a_rate"], d["pass_rate"]])
    w.writerow([])
    w.writerow(["高频扣分条款", "次数", "条款说明"])
    for r in data["top_rules"]:
        w.writerow([_csv_safe(r["rule_code"]), r["count"], _csv_safe(r["description"])])
    w.writerow([])
    w.writerow(["复核通过", data["reviews"]["passed"]])
    w.writerow(["退回整改", data["reviews"]["returned"]])
    ap = data["archive_proxy"]
    w.writerow(["归档时效（代理口径）",
                f"{ap['ok']}/{ap['total']}" if ap["total"] else "无样本",
                ap["caliber"]])
    # UTF-8 BOM 让 Excel 正确识别中文
    content = "﻿" + buf.getvalue()
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=qc_stats.csv"},
    )
