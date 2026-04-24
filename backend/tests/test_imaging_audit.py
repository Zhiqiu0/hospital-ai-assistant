"""影像报告审计字段测试（models/imaging.py）

回归保护 S2 修复：publish_report 不应再覆盖 radiologist_id。
关键不变量：
  - radiologist_id 在 analyze 阶段写入，publish 阶段必须保持原值
  - published_by 由 publish 阶段写入，可以与 radiologist_id 不同（A 分析 + B 签发）

注：完整的端点级集成测试待 backlog M5 补上 PACS 集成测试时统一做，
本用例从 ORM 层验证字段可独立写入，确保 schema_compat 已加列、字段未被
误标 unique 等约束。
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.imaging import ImagingReport, ImagingStudy
from app.models.patient import Patient
from app.models.user import User


@pytest.mark.asyncio
async def test_published_by_can_differ_from_radiologist_id(async_db):
    """A 分析（radiologist_id=A）→ B 签发（published_by=B），两个字段必须能独立保存。"""
    pat = Patient(id="pat-img-1", name="影像患者")
    rad_a = User(
        id="rad-a",
        username="rad_a",
        password_hash="x",
        real_name="放射 A",
        role="radiologist",
    )
    rad_b = User(
        id="rad-b",
        username="rad_b",
        password_hash="x",
        real_name="放射 B",
        role="radiologist",
    )
    study = ImagingStudy(
        id="study-1",
        patient_id=pat.id,
        uploaded_by=rad_a.id,
        modality="CT",
        storage_dir="/tmp/study1",
        total_frames=10,
        status="analyzed",
    )
    async_db.add_all([pat, rad_a, rad_b, study])
    await async_db.flush()

    # 分析阶段：A 写入 radiologist_id
    report = ImagingReport(
        study_id=study.id,
        radiologist_id=rad_a.id,
        ai_analysis="AI 初步分析",
        final_report="AI 初步分析",
    )
    async_db.add(report)
    await async_db.commit()

    # 签发阶段：B 来发布——只改 published_by + is_published + published_at
    fetched = (
        await async_db.execute(
            select(ImagingReport).where(ImagingReport.study_id == study.id)
        )
    ).scalar_one()
    fetched.final_report = "B 复核后的最终报告"
    fetched.is_published = True
    fetched.published_at = datetime(2026, 4, 25, 10, 0)
    fetched.published_by = rad_b.id
    await async_db.commit()

    # 关键不变量
    refetched = (
        await async_db.execute(
            select(ImagingReport).where(ImagingReport.study_id == study.id)
        )
    ).scalar_one()
    assert refetched.radiologist_id == rad_a.id, "分析人不应被签发覆盖"
    assert refetched.published_by == rad_b.id
    assert refetched.is_published is True
    assert refetched.published_at == datetime(2026, 4, 25, 10, 0)


@pytest.mark.asyncio
async def test_published_by_nullable_when_not_published(async_db):
    """未发布的报告 published_by 应保持 NULL，不阻塞 analyze 流程。"""
    pat = Patient(id="pat-img-2", name="影像患者2")
    rad = User(
        id="rad-x", username="rad_x", password_hash="x", real_name="放射 X", role="radiologist"
    )
    study = ImagingStudy(
        id="study-2",
        patient_id=pat.id,
        uploaded_by=rad.id,
        storage_dir="/tmp/study2",
        status="analyzed",
    )
    report = ImagingReport(study_id=study.id, radiologist_id=rad.id, ai_analysis="AI")
    async_db.add_all([pat, rad, study, report])
    await async_db.commit()

    refetched = (
        await async_db.execute(
            select(ImagingReport).where(ImagingReport.study_id == study.id)
        )
    ).scalar_one()
    assert refetched.published_by is None
    assert refetched.is_published is False
