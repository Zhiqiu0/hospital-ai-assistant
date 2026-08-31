# -*- coding: utf-8 -*-
"""第 16 轮审计的守卫回归锁（2026-09-01）。

三个来源不同但同属"声明与实现不符"的问题：
  · 问诊数据签发后仍可改 → 绕过签名链、HIS 病案与签发件永久分叉
  · 患者读端点注释写"医生"、实现放行全角色 → PHI 越界
  · HIS 姓名为 null 整条接诊被拒 → 与规范的容错承诺矛盾，急诊无名氏推不进来
"""
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.core.authz import PATIENT_LIST_ROLES, PATIENT_READ_ROLES, assert_can_read_patient
from app.his_adapter.models import AdmitPushRequest
from app.models.encounter import Encounter
from app.models.medical_record import MedicalRecord
from app.models.patient import Patient
from app.schemas.encounter import InquiryInputUpdate
from app.services.encounter_service import EncounterService


class _U:
    def __init__(self, role):
        self.role = role
        self.id = "u-1"


# ── 一、问诊数据的签发冻结 ────────────────────────────────────────────────

async def _mk(db, *, visit_type: str, signed: bool, completed: bool = False) -> str:
    patient = Patient(name="孙七", gender="male")
    db.add(patient)
    await db.flush()
    enc = Encounter(patient_id=patient.id, doctor_id="doc-1", visit_type=visit_type,
                    visited_at=datetime.now(),
                    status="completed" if completed else "in_progress")
    db.add(enc)
    await db.flush()
    if signed:
        db.add(MedicalRecord(encounter_id=enc.id, record_type="outpatient",
                             status="submitted", current_version=1, record_no=1))
    await db.commit()
    return enc.id


@pytest.mark.asyncio
async def test_门急诊签发后问诊数据不可再改(async_db):
    """HIS 回写的 record.*/vitals.* 是推送那一刻从 InquiryInput 实时重建的，
    而 sign_hash 不覆盖这些结构化字段——签发后改这里等于一条绕过防篡改体系的
    写通道，且会让 HIS 病案与我方签发件永久不一致。"""
    enc_id = await _mk(async_db, visit_type="outpatient", signed=True)
    with pytest.raises(HTTPException) as ei:
        await EncounterService(async_db).save_inquiry(
            enc_id, InquiryInputUpdate(chief_complaint="改过的主诉"))
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_住院未出院时问诊数据仍可改(async_db):
    """住院一次接诊有多份文书、持续录入，签了第一份不能就此锁死。"""
    enc_id = await _mk(async_db, visit_type="inpatient", signed=True)
    res = await EncounterService(async_db).save_inquiry(
        enc_id, InquiryInputUpdate(chief_complaint="住院持续录入"))
    assert res is not None


@pytest.mark.asyncio
async def test_住院出院后问诊数据冻结(async_db):
    enc_id = await _mk(async_db, visit_type="inpatient", signed=True, completed=True)
    with pytest.raises(HTTPException) as ei:
        await EncounterService(async_db).save_inquiry(
            enc_id, InquiryInputUpdate(chief_complaint="出院后还改"))
    assert ei.value.status_code == 403


# ── 二、患者 PHI 读取的角色边界 ───────────────────────────────────────────

@pytest.mark.parametrize("role", ["doctor", "super_admin", "hospital_admin", "dept_admin"])
def test_医生与管理角色可读患者详情(role):
    assert_can_read_patient(_U(role))


@pytest.mark.parametrize("role", ["nurse", "qc_officer", "radiologist"])
def test_其余角色不得读患者详情与档案(role):
    """身份证/住址/紧急联系人/过敏史。"全院共享不拦读"的论证前提是面向医生
    （代班/转诊/复诊换医生是常态），不适用于这三个角色。"""
    with pytest.raises(HTTPException) as ei:
        assert_can_read_patient(_U(role))
    assert ei.value.status_code == 403


def test_影像科保留患者列表权限():
    """PACS 上传要在下拉里选患者——收紧不能把这条既有功能打断。"""
    assert_can_read_patient(_U("radiologist"), list_only=True)


@pytest.mark.parametrize("role", ["nurse", "qc_officer"])
def test_护士与质控员连列表也不给(role):
    with pytest.raises(HTTPException):
        assert_can_read_patient(_U(role), list_only=True)


def test_列表白名单只比详情多影像科():
    assert PATIENT_LIST_ROLES - PATIENT_READ_ROLES == {"radiologist"}


# ── 三、HIS 推送的姓名容错 ───────────────────────────────────────────────

@pytest.mark.parametrize("kw", [
    {"visit_id": "V1", "hospital_code": "H1", "patient_name": None},
    {"visit_id": "V1", "hospital_code": "H1"},
])
def test_姓名为空的推送不得整条拒收(kw):
    """规范承诺"不会因类型/编码差异导致整条推送被拒"；急诊三无人员在 HIS 里
    姓名列就是 NULL，拒收等于最该马上接诊的人反而进不了工作台。
    降级由 admit_service 的占位名路径接管。"""
    req = AdmitPushRequest(**kw)
    assert req.patient_name is None


def test_必填的两个键仍然必填():
    """放宽姓名不等于什么都收——visit_id/hospital_code 是幂等键，缺了无法处理。"""
    with pytest.raises(Exception):
        AdmitPushRequest(hospital_code="H1", patient_name="张三")
