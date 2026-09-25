"""已发布影像报告不可无版本覆写；以真实数据库和保存路由验证审计边界。"""
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.api.v1.pacs_reports import SaveReportRequest, save_report
from app.models.imaging import ImagingReport, ImagingStudy
from app.models.patient import Patient
from app.models.user import User


@pytest.fixture
async def published_report(async_db):
    """只有合成影像索引，无真实DICOM或外部服务。"""
    patient = Patient(id='pacs-patient', name='合成验收患者')
    doctor = User(id='pacs-doctor', username='pacs-doctor', real_name='合成影像医生', password_hash='test', role='radiologist')
    study = ImagingStudy(id='pacs-study', patient_id=patient.id, uploaded_by=doctor.id, status='published')
    report = ImagingReport(study_id=study.id, radiologist_id=doctor.id,
                           final_report='已复核的合成报告A', ai_analysis='合成AI结果',
                           is_published=True, published_by=doctor.id,
                           published_at=datetime(2026, 9, 26, 10, 0))
    async_db.add_all([patient, doctor, study, report])
    await async_db.commit()
    return doctor, study, report


@pytest.mark.parametrize('publish', [False, True])
async def test_published_report_rejects_overwrite(async_db, published_report, publish):
    """草稿保存或再次发布都不能让新正文冒用既有发布审计信息。"""
    doctor, study, report = published_report
    with pytest.raises(HTTPException) as caught:
        await save_report(study.id, SaveReportRequest(final_report='未签发正文B', publish=publish),
                          db=async_db, current_user=doctor)
    assert caught.value.status_code == 409
    await async_db.refresh(report)
    assert report.final_report == '已复核的合成报告A'
    assert report.published_at == datetime(2026, 9, 26, 10, 0)
    assert report.is_published


async def test_unpublished_report_can_save_then_publish(async_db, published_report):
    """普通草稿编辑及首次发布不受已发布保护影响。"""
    doctor, study, report = published_report
    report.is_published = False
    report.published_at = None
    report.published_by = None
    study.status = 'analyzed'
    await async_db.commit()
    await save_report(study.id, SaveReportRequest(final_report='复核草稿', publish=False),
                      db=async_db, current_user=doctor)
    assert report.final_report == '复核草稿'
    assert not report.is_published
    result = await save_report(study.id, SaveReportRequest(final_report='复核终稿', publish=True),
                               db=async_db, current_user=doctor)
    assert result['published_at']
    assert report.is_published and study.status == 'published'
    assert report.final_report == '复核终稿'


async def test_identical_publish_retry_keeps_original_timestamp(async_db, published_report):
    """客户端丢失成功响应后重试相同发布，幂等返回且不重写签发时间。"""
    doctor, study, report = published_report
    response = await save_report(study.id, SaveReportRequest(final_report=report.final_report, publish=True),
                                 db=async_db, current_user=doctor)
    assert response['published_at'] == '2026-09-26T10:00:00'
    await async_db.refresh(report)
    assert report.published_at == datetime(2026, 9, 26, 10, 0)
