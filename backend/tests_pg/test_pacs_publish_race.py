"""真实PG验证PACS发布/分析/删除互斥；只使用一次性测试库，Orthanc全替身。"""
import asyncio
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import pacs_reports as routes
from app.models.imaging import ImagingStudy, ImagingReport
from app.models.patient import Patient
from app.models.user import User
from app.services.pacs.report_service import upsert_analysis_report


class PausedReportSession(AsyncSession):
    """报告行已锁住时暂停发布，精确安排删除竞争，不依赖固定sleep。"""
    async def execute(self, statement, *args, **kwargs):
        result = await super().execute(statement, *args, **kwargs)
        gate = self.info.pop("pause_report", None) if (
            any(column.get("entity") is ImagingReport for column in getattr(statement, "column_descriptions", []))
        ) else None
        if gate:
            acquired, release = gate
            acquired.set()
            await release.wait()
        return result


@pytest.fixture
async def report_context(alembic_pg, monkeypatch):
    """迁移后的真PG约束和两个独立事务；合成标识不引用真实影像。"""
    session_factory = async_sessionmaker(alembic_pg, class_=PausedReportSession, expire_on_commit=False)
    async with session_factory() as db:
        doctor = User(id=str(uuid4()), username=f"pacs-{uuid4().hex}", real_name="合成影像医生",
                      password_hash="fake", role="radiologist")
        patient = Patient(id=str(uuid4()), name="合成并发患者")
        db.add_all([doctor, patient])
        await db.flush()
        study = ImagingStudy(id=str(uuid4()), patient_id=patient.id, uploaded_by=doctor.id,
                             study_instance_uid="1.2.826.0.1.3680043.10.999", status="analyzed")
        db.add(study)
        await db.flush()
        db.add(ImagingReport(study_id=study.id, radiologist_id=doctor.id,
                             final_report="合成草稿", ai_analysis="合成分析", is_published=False))
        await db.commit()
    orthanc = AsyncMock()
    monkeypatch.setattr(routes.orthanc_client, "delete_study", orthanc)
    monkeypatch.setattr(routes.render_cache, "clear_study_cache", AsyncMock())
    return alembic_pg, session_factory, doctor, study.id, orthanc


async def wait_until_pg_blocked(engine, pid):
    """由PG实际锁等待确认竞争已发生；轮询SQL自身让出事件循环，无定时猜测。"""
    async with asyncio.timeout(5):
        async with engine.connect() as conn:
            while not await conn.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}):
                pass


async def run_transaction(db, operation):
    """失败必须立即回滚释放锁，否则一个失败会让另一事务永远等下去。"""
    try:
        return await operation
    except Exception as exc:
        await db.rollback()
        return exc


async def cancel_tasks(tasks):
    """断言失败或超时同样清理所有并发事务。"""
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_publish_wins_before_delete(report_context):
    """发布先锁定后，删除必须409且绝不能触碰Orthanc原始影像。"""
    engine, session_factory, doctor, study_id, orthanc = report_context
    acquired, release = asyncio.Event(), asyncio.Event()
    tasks = []
    async with session_factory() as publisher, session_factory() as deleter:
        delete_pid = await deleter.scalar(text("SELECT pg_backend_pid()"))
        publisher.info["pause_report"] = (acquired, release)
        try:
            tasks.append(asyncio.create_task(run_transaction(publisher, routes.save_report(
                study_id, routes.SaveReportRequest(final_report="已复核终稿", publish=True), publisher, doctor))))
            await asyncio.wait_for(acquired.wait(), 5)
            tasks.append(asyncio.create_task(run_transaction(deleter, routes.delete_study(study_id, deleter, doctor))))
            await wait_until_pg_blocked(engine, delete_pid)
            release.set()
            published, deleted = await asyncio.wait_for(asyncio.gather(*tasks), 8)
            assert isinstance(published, dict) and published.get("published_at")
            assert isinstance(deleted, HTTPException) and deleted.status_code == 409
            orthanc.assert_not_awaited()
        finally:
            release.set()
            await cancel_tasks(tasks)
    async with session_factory() as check:
        report = (await check.execute(select(ImagingReport).where(ImagingReport.study_id == study_id))).scalar_one()
        assert report.is_published and report.final_report == "已复核终稿"


@pytest.mark.parametrize("writer_kind", ["publish", "analyze"])
async def test_delete_wins_before_writer(report_context, writer_kind):
    """删除先锁定时，发布404/分析410，不留下幽灵报告或报告→检查反向锁环。"""
    engine, session_factory, doctor, study_id, orthanc = report_context
    deleting, release = asyncio.Event(), asyncio.Event()

    async def pause_remote_delete(*_args):
        deleting.set()
        await release.wait()

    orthanc.side_effect = pause_remote_delete
    tasks = []
    async with session_factory() as deleter, session_factory() as writer:
        writer_pid = await writer.scalar(text("SELECT pg_backend_pid()"))
        study = await writer.get(ImagingStudy, study_id)
        try:
            tasks.append(asyncio.create_task(run_transaction(deleter, routes.delete_study(study_id, deleter, doctor))))
            await asyncio.wait_for(deleting.wait(), 5)
            operation = (routes.save_report(study_id, routes.SaveReportRequest(final_report="迟到终稿", publish=True), writer, doctor)
                         if writer_kind == "publish" else
                         upsert_analysis_report(writer, study, study_id, [], "迟到分析", doctor.id))
            tasks.append(asyncio.create_task(run_transaction(writer, operation)))
            await wait_until_pg_blocked(engine, writer_pid)
            release.set()
            deleted, written = await asyncio.wait_for(asyncio.gather(*tasks), 8)
            assert isinstance(deleted, dict) and deleted.get("ok")
            assert isinstance(written, HTTPException)
            assert written.status_code == (404 if writer_kind == "publish" else 410)
            orthanc.assert_awaited_once()
        finally:
            release.set()
            await cancel_tasks(tasks)
    async with session_factory() as check:
        assert await check.get(ImagingStudy, study_id) is None
        assert (await check.execute(select(ImagingReport).where(ImagingReport.study_id == study_id))).scalar_one_or_none() is None
