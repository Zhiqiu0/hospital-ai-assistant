"""授权辅助（core/authz.py）测试

PACS thumbnail/dicom/frames 三个端点曾完全无鉴权，修复时统一接入
assert_patient_access。本用例覆盖该辅助的角色直通 / 跨患者拒绝 /
本医生放行三种关键场景，回归保护 PACS 鉴权决策的正确性。
"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.authz import assert_encounter_access, assert_pacs_write
from app.models.encounter import Encounter
from app.models.patient import Patient


def _user(uid: str, role: str = "doctor"):
    """构造一个轻量用户对象，供 authz 函数使用（authz 只读 id/role 属性）。"""
    return SimpleNamespace(id=uid, role=role)


# assert_patient_access 已随 2026-08-29 第七轮审计删除（生产零调用死码），
# 其测试一并移除；读权现行口径=开放读+审计，写权见 assert_patient_write_access。


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
