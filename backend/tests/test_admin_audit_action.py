# -*- coding: utf-8 -*-
"""admin 审计的 action 必须是路由模板（2026-09-02 审计日志专项）。

生产实测：281 条 admin 审计产生了 34 种 action 取值——每停用一个账号、每修订
一份病历都新增一种，因为 action 里写的是含 UUID 的实际路径：

    admin:DELETE:/api/v1/admin/users/7893e1e0-1ed3-4c14-baa1-8a49d0c4dbee
    admin:POST:/api/v1/admin/records/826a20cd-.../revise

而 resource_id 列反倒全空（0/281）。后果是审计日志最基本的用途当场失效：
想查"本月发生过几次病历修订"，GROUP BY action 得到的是一堆各不相同的 URL；
等级保护测评和医院评审要的正是这种按操作类型的统计。

两个维度各归其位：action 用稳定的路由模板，实际资源 ID 进 resource_id。
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.audit_dep import audit_admin_action


def _request(method: str, real_path: str, route_path: str, params: dict):
    """构造一个足够 audit_admin_action 使用的假 Request。"""
    return SimpleNamespace(
        method=method,
        url=SimpleNamespace(path=real_path),
        scope={"route": SimpleNamespace(path=route_path)},
        path_params=params,
        headers={},
        client=SimpleNamespace(host="10.0.0.9"),
    )


async def _run(request) -> dict:
    user = SimpleNamespace(id="adm-1", username="admin", role="hospital_admin")
    with patch("app.core.audit_dep.log_action", new=AsyncMock()) as spy:
        gen = audit_admin_action(request, user)
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
    return spy.await_args.kwargs


@pytest.mark.asyncio
async def test_停用账号的action不含uuid():
    kwargs = await _run(_request(
        "DELETE",
        "/api/v1/admin/users/7893e1e0-1ed3-4c14-baa1-8a49d0c4dbee",
        "/api/v1/admin/users/{user_id}",
        {"user_id": "7893e1e0-1ed3-4c14-baa1-8a49d0c4dbee"}))
    assert kwargs["action"] == "admin:DELETE:/api/v1/admin/users/{user_id}"
    assert "7893e1e0" not in kwargs["action"], "资源 UUID 又跑进 action 了"
    assert kwargs["resource_id"] == "7893e1e0-1ed3-4c14-baa1-8a49d0c4dbee"


@pytest.mark.asyncio
async def test_病历修订的action可聚合():
    """三次修订三份不同病历，action 必须是同一个值，否则统计不出"修订次数"。"""
    actions = set()
    for rid in ("826a20cd", "f1e6e422", "96ccc6b7"):
        kwargs = await _run(_request(
            "POST", f"/api/v1/admin/records/{rid}/revise",
            "/api/v1/admin/records/{record_id}/revise", {"record_id": rid}))
        actions.add(kwargs["action"])
    assert len(actions) == 1, f"三次修订产生了 {len(actions)} 种 action：{actions}"


@pytest.mark.asyncio
async def test_无路径参数的端点不受影响():
    kwargs = await _run(_request(
        "POST", "/api/v1/admin/users", "/api/v1/admin/users", {}))
    assert kwargs["action"] == "admin:POST:/api/v1/admin/users"
    assert kwargs["resource_id"] is None


@pytest.mark.asyncio
async def test_端点抛异常也要留痕且标记失败():
    """管理员"尝试做某事但失败"同样是合规事件（越权尝试正是要查的）。"""
    user = SimpleNamespace(id="adm-1", username="admin", role="dept_admin")
    req = _request("DELETE", "/api/v1/admin/users/x",
                   "/api/v1/admin/users/{user_id}", {"user_id": "x"})
    with patch("app.core.audit_dep.log_action", new=AsyncMock()) as spy:
        gen = audit_admin_action(req, user)
        await gen.__anext__()
        with pytest.raises(RuntimeError):
            await gen.athrow(RuntimeError("越权被拒"))
    assert spy.await_args.kwargs["status"] == "fail"


# ─── 审计检索：时间范围与对象过滤 ────────────────────────────────────
#
# 审计页原先只有关键词 + 操作类型，列表按时间倒序翻页——开业后 40 位医生一个月
# 上万条，医务科要查"上个月谁改过病历"只能一页页翻，实际用不了。纠纷追溯更需要
# "这份病历被谁碰过"，那正是 resource_id 维度（#265 刚让它有值）。

from datetime import date, datetime, time, timedelta

from app.models.audit_log import AuditLog


@pytest.mark.asyncio
async def test_日期范围含当天整日(async_db):
    """结束日必须取到 23:59:59。只比日期零点的话，"查 8月31 日"会漏掉那天所有
    非零点的记录——审计场景下漏记录等于漏证。"""
    from app.api.v1.admin.audit_logs import list_audit_logs

    today = date.today()
    async_db.add_all([
        AuditLog(id="a1", user_id="u1", user_name="张三", user_role="doctor",
                 action="sign_record", created_at=datetime.combine(today, time(23, 59, 30))),
        AuditLog(id="a2", user_id="u1", user_name="张三", user_role="doctor",
                 action="sign_record",
                 created_at=datetime.combine(today - timedelta(days=5), time(9, 0))),
    ])
    await async_db.commit()

    res = await list_audit_logs(
        keyword="", action="", start_date=today.isoformat(),
        end_date=today.isoformat(), resource_id="", page=1, page_size=20,
        db=async_db, current_user=None)
    ids = {i["id"] for i in res["items"]}
    assert "a1" in ids, "当天 23:59 的记录被日期上界漏掉了"
    assert "a2" not in ids, "范围外的记录被带了进来"


@pytest.mark.asyncio
async def test_按操作对象过滤(async_db):
    """纠纷追溯的典型查询：这份病历被谁碰过。"""
    from app.api.v1.admin.audit_logs import list_audit_logs

    async_db.add_all([
        AuditLog(id="b1", user_id="u1", user_name="张三", user_role="doctor",
                 action="revise_record", resource_id="rec-42", created_at=datetime.now()),
        AuditLog(id="b2", user_id="u2", user_name="李四", user_role="admin",
                 action="revise_record", resource_id="rec-99", created_at=datetime.now()),
    ])
    await async_db.commit()
    res = await list_audit_logs(
        keyword="", action="", start_date="", end_date="", resource_id="rec-42",
        page=1, page_size=20, db=async_db, current_user=None)
    assert [i["id"] for i in res["items"]] == ["b1"]


@pytest.mark.asyncio
async def test_日期填错不炸只忽略(async_db):
    """管理员手滑输入非法日期，不该让整页查询变成 500。"""
    from app.api.v1.admin.audit_logs import list_audit_logs

    async_db.add(AuditLog(id="c1", user_id="u1", user_name="张三", user_role="doctor",
                          action="login", created_at=datetime.now()))
    await async_db.commit()
    res = await list_audit_logs(
        keyword="", action="", start_date="2026-13-99", end_date="不是日期",
        resource_id="", page=1, page_size=20, db=async_db, current_user=None)
    assert res["total"] >= 1
