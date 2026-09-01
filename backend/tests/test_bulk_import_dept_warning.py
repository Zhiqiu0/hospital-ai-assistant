# -*- coding: utf-8 -*-
"""批量开户：科室名没匹配上必须让管理员看见（2026-09-02 开业配置动线实测）。

原实现 department_id=dept_map.get(name)，匹配不上就静静落 None，而这一行的
status 仍是 created、message 为空——管理员看到的是"全部成功"。

名单里的科室名与系统建制不完全一致是常态（"内一科"对"内科"、"外科（普外）"、
多一个空格）。濮氏这次要一次导入 40 位临床医生 53 个工号，管理员没有任何线索
知道哪几位落了空科室。空科室不是显示问题：科室质控员按 department_id 限定复核
范围（qc/reviews._dept_scope），看不到这些医生的病历；科室维度的达标率统计
同样漏掉他们。
"""
import pytest

from app.models.user import Department, User
from app.schemas.user import BulkImportDoctorItem, BulkImportRequest
from app.services.user_bulk_import import bulk_import_doctors as bulk_import_doctors_service


def _admin() -> User:
    return User(id="adm-1", username="adm", password_hash="x", real_name="院管",
                role="hospital_admin", is_active=True)


async def _run(db, *, dept_name, dry_run=False):
    db.add(Department(id="d-nk", name="内科", code="NK"))
    await db.commit()
    req = BulkImportRequest(
        items=[BulkImportDoctorItem(real_name="张三", codes=["T9001"],
                                    department_name=dept_name, role="doctor")],
        initial_password="MediScribe@2026", dry_run=dry_run)
    return await bulk_import_doctors_service(db, req, _admin())


@pytest.mark.asyncio
async def test_科室名不存在要在结果里说明(async_db):
    res = await _run(async_db, dept_name="内一科")
    item = res.items[0] if hasattr(res, "items") else res["items"][0]
    msg = item.message if hasattr(item, "message") else item["message"]
    assert msg and "内一科" in msg, "科室没匹配上却没有任何提示"
    assert "留空" in msg


@pytest.mark.asyncio
async def test_科室名匹配得上不加噪音(async_db):
    res = await _run(async_db, dept_name="内科")
    item = res.items[0] if hasattr(res, "items") else res["items"][0]
    msg = item.message if hasattr(item, "message") else item["message"]
    assert not msg, f"匹配成功的行不该有提示，实际：{msg}"


@pytest.mark.asyncio
async def test_未指定科室也要标出来(async_db):
    """名单里那一列本来就是空的，同样会落空科室，管理员该知道。"""
    res = await _run(async_db, dept_name=None)
    item = res.items[0] if hasattr(res, "items") else res["items"][0]
    msg = item.message if hasattr(item, "message") else item["message"]
    assert msg and "未指定科室" in msg


@pytest.mark.asyncio
async def test_干跑预览同样给出科室提示(async_db):
    """导入前的预览正是发现这类问题的地方，不能只在落库后才说。"""
    res = await _run(async_db, dept_name="内一科", dry_run=True)
    item = res.items[0] if hasattr(res, "items") else res["items"][0]
    msg = item.message if hasattr(item, "message") else item["message"]
    assert "预览" in msg and "内一科" in msg
