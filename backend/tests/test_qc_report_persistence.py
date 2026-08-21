# -*- coding: utf-8 -*-
"""qc_reports 评分落库测试（2026-08-21 阶段0）。

验证：评分权威结果（分数/等级/扣分明细含 rule_code/科室医生冗余快照）
正确写入 qc_reports；按 (encounter, record_type) 定位文书与 save_qc_issues 同口径。
"""
from datetime import date, datetime

import pytest
from sqlalchemy import select

import app.services.ai.task_logger as task_logger
from app.models.encounter import Encounter
from app.models.medical_record import QCReport
from app.models.patient import Patient
from app.services.medical_record_service import MedicalRecordService


@pytest.mark.asyncio
async def test_save_qc_report_persists_full_row(async_db, monkeypatch):
    """评分落库：分数/等级/明细/冗余科室医生列全部写入。"""
    async_db.add(Patient(id="p1", name="张三", birth_date=date(1970, 1, 1)))
    async_db.add(Encounter(
        id="enc-1", patient_id="p1", doctor_id="doc-1", department_id="dept-9",
        visit_type="inpatient", status="in_progress", visited_at=datetime(2026, 8, 20),
    ))
    await async_db.flush()
    # 建一份该类型的病历行，验证 medical_record 关联定位
    svc = MedicalRecordService(async_db)
    saved = await svc.save_ai_draft("enc-1", "admission_note", "入院记录草稿", "doc-1")

    # save_qc_report 用独立 AsyncSessionLocal——测试里替换成测试库会话工厂
    class _Factory:
        def __call__(self):
            return self
        async def __aenter__(self):
            return async_db
        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(task_logger, "AsyncSessionLocal", _Factory())

    await task_logger.save_qc_report(
        {"score": 91.0, "grade": "乙级", "passed": True},
        deductions=[{
            "rule_code": "IP-ADMIT-03", "item_name": "体格检查", "target_field": "望诊",
            "points": 3, "is_veto": False, "description": "缺望诊描述",
        }],
        rubric_key="zj_inpatient_2021",
        encounter_id="enc-1",
        record_type="admission_note",
    )

    row = (await async_db.execute(select(QCReport))).scalar_one()
    assert row.score == 91.0
    assert row.grade == "乙级"
    assert row.passed is True
    assert row.rubric_key == "zj_inpatient_2021"
    assert row.record_type == "admission_note"
    assert row.encounter_id == "enc-1"
    assert row.medical_record_id == saved["record_id"], "应定位到同类型那份文书"
    assert row.department_id == "dept-9" and row.doctor_id == "doc-1", "科室/医生冗余快照缺失"
    assert row.deductions[0]["rule_code"] == "IP-ADMIT-03", "扣分明细必须带法定条款代码"


@pytest.mark.asyncio
async def test_save_qc_report_without_encounter_still_persists(async_db, monkeypatch):
    """无接诊上下文的裸评分也要留痕（关联列为空）。"""
    class _Factory:
        def __call__(self):
            return self
        async def __aenter__(self):
            return async_db
        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(task_logger, "AsyncSessionLocal", _Factory())

    await task_logger.save_qc_report(
        {"score": 74.0, "grade": "不合格", "passed": False},
        deductions=[], rubric_key="zj_outpatient_emergency_2023",
        encounter_id=None, record_type="outpatient",
    )
    row = (await async_db.execute(select(QCReport))).scalar_one()
    assert row.score == 74.0 and row.encounter_id is None and row.passed is False
