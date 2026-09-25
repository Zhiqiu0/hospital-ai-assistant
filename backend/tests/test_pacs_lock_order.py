"""PACS发布/分析的锁协议：SQLite验证调用顺序，SQL按PG方言编译验证行锁。"""
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import dialect

from app.api.v1.pacs_reports import SaveReportRequest, save_report
from app.models.imaging import ImagingStudy, ImagingReport
from app.services.pacs.report_service import upsert_analysis_report
from test_pacs_published_report import published_report  # noqa: F401


@pytest.mark.parametrize("operation", ["publish", "analyze"])
async def test_report_writers_lock_study_before_report(async_db, published_report, monkeypatch, operation):
    """所有写者都先锁同一父行，避免与删除的study→report顺序构成锁环。"""
    doctor, study, report = published_report
    operations = []
    original_get, original_execute = async_db.get, async_db.execute

    async def get(entity, identity, **kwargs):
        if entity is ImagingStudy:
            operations.append(("study", kwargs.get("with_for_update"), kwargs.get("populate_existing")))
        return await original_get(entity, identity, **kwargs)

    async def execute(statement, *args, **kwargs):
        if "imaging_reports" in str(statement):
            operations.append(("report", str(statement.compile(dialect=dialect()))))
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(async_db, "get", get)
    monkeypatch.setattr(async_db, "execute", execute)
    if operation == "publish":
        await save_report(study.id, SaveReportRequest(final_report=report.final_report, publish=True), async_db, doctor)
    else:
        await upsert_analysis_report(async_db, study, study.id, [], "新的合成AI分析", doctor.id)
    assert operations[0] == ("study", True, True)
    assert operations[1][0] == "report"
    assert "FOR UPDATE" in operations[1][1]


async def test_analysis_cannot_recreate_deleted_study(async_db, published_report):
    """长模型调用持有的旧study对象不能用于已删除检查的新报告写入。"""
    doctor, study, report = published_report
    study_id = study.id
    await async_db.delete(report)
    await async_db.delete(study)
    await async_db.commit()
    with pytest.raises(HTTPException) as caught:
        await upsert_analysis_report(async_db, study, study_id, [], "迟到分析", doctor.id)
    assert caught.value.status_code == 410
