"""授权辅助（core/authz.py）测试

PACS thumbnail/dicom/frames 三个端点曾完全无鉴权，修复时统一接入
assert_patient_access。本用例覆盖该辅助的角色直通 / 跨患者拒绝 /
本医生放行三种关键场景，回归保护 PACS 鉴权决策的正确性。
"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.authz import assert_encounter_access, assert_pacs_write, assert_patient_access
from app.models.encounter import Encounter
from app.models.patient import Patient


def _user(uid: str, role: str = "doctor"):
    """构造一个轻量用户对象，供 authz 函数使用（authz 只读 id/role 属性）。"""
    return SimpleNamespace(id=uid, role=role)


# ── assert_patient_access ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patient_access_radiologist_passes_without_db(async_db):
    """放射科医生对任意患者直通，不查 DB。"""
    # 即使该患者不存在也应通过——验证零 DB 查询路径
    await assert_patient_access(async_db, "no-such-patient", _user("rad-1", role="radiologist"))


@pytest.mark.asyncio
async def test_patient_access_admin_passes_without_db(async_db):
    """三种 admin 角色同样直通。"""
    for role in ("super_admin", "hospital_admin", "dept_admin"):
        await assert_patient_access(async_db, "no-such-patient", _user(f"u-{role}", role=role))


@pytest.mark.asyncio
async def test_patient_access_doctor_with_encounter_passes(async_db):
    """普通医生对自己接诊过的患者放行。"""
    pat = Patient(id="pat-doc-ok", name="测试患者")
    enc = Encounter(
        id="enc-doc-ok",
        patient_id=pat.id,
        doctor_id="doc-me",
        visit_type="outpatient",
        status="completed",
        visited_at=datetime(2026, 4, 1),
    )
    async_db.add_all([pat, enc])
    await async_db.commit()

    await assert_patient_access(async_db, pat.id, _user("doc-me"))


@pytest.mark.asyncio
async def test_patient_access_doctor_without_encounter_blocked(async_db):
    """普通医生对没接诊过的患者拒绝（403）。"""
    pat = Patient(id="pat-doc-other", name="他人患者")
    enc = Encounter(
        id="enc-other",
        patient_id=pat.id,
        doctor_id="doc-other",
        visit_type="outpatient",
        status="completed",
        visited_at=datetime(2026, 4, 1),
    )
    async_db.add_all([pat, enc])
    await async_db.commit()

    with pytest.raises(HTTPException) as exc:
        await assert_patient_access(async_db, pat.id, _user("doc-me"))
    assert exc.value.status_code == 403


# ── assert_pacs_write ─────────────────────────────────────────────────────────

def test_pacs_write_allows_radiologist_and_admins():
    """PACS 写权限只放行放射科医生和三种 admin。"""
    for role in ("radiologist", "super_admin", "hospital_admin", "dept_admin"):
        assert_pacs_write(_user("u", role=role))


def test_pacs_write_blocks_doctor_and_nurse():
    """普通临床医生 / 护士不允许做 PACS 写操作。"""
    for role in ("doctor", "nurse", ""):
        with pytest.raises(HTTPException) as exc:
            assert_pacs_write(_user("u", role=role))
        assert exc.value.status_code == 403


# ── assert_encounter_access ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_encounter_access_404_when_not_exists(async_db):
    """接诊不存在时返回 404，不暴露存在性差异。"""
    with pytest.raises(HTTPException) as exc:
        await assert_encounter_access(async_db, "no-such-enc", _user("doc-me"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_encounter_access_admin_returns_object(async_db):
    """admin 直通且返回 Encounter 对象供调用方复用。"""
    enc = Encounter(
        id="enc-admin",
        patient_id="pat-x",
        doctor_id="doc-other",
        visit_type="outpatient",
        status="in_progress",
        visited_at=datetime(2026, 4, 1),
    )
    async_db.add(enc)
    await async_db.commit()

    got = await assert_encounter_access(async_db, enc.id, _user("admin", role="super_admin"))
    assert got.id == "enc-admin"


@pytest.mark.asyncio
async def test_encounter_access_other_doctor_blocked(async_db):
    """非接诊医生本人访问返回 403。"""
    enc = Encounter(
        id="enc-mine",
        patient_id="pat-y",
        doctor_id="doc-owner",
        visit_type="outpatient",
        status="in_progress",
        visited_at=datetime(2026, 4, 1),
    )
    async_db.add(enc)
    await async_db.commit()

    with pytest.raises(HTTPException) as exc:
        await assert_encounter_access(async_db, enc.id, _user("doc-other"))
    assert exc.value.status_code == 403
