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
