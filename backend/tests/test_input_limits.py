# -*- coding: utf-8 -*-
"""超长输入边界（2026-09-10 收敛验证轮 · 角度 D）。

生产实测两条实锤：直连 API 传 500 字姓名 → 穿过校验直插 String(50) 列、
DataError 炸 500（HIS 入站早按列宽截断，直连这条漏了——同一红线要覆盖所有
入口）；5MB 病历正文一路 200 落库，而每次编辑/签发都把全文整份复制进
record_versions。修法：姓名按列宽 422 拒绝（不截断——医生主动录入的身份字段
静默截掉会造出错名字的档案），正文 50 万字符上限（宽松到不可能误伤真病历）。
"""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.encounter import QuickStartRequest
from app.schemas.medical_record import AutoSaveDraftRequest


def test_姓名超列宽被422拒绝而不是炸500():
    with pytest.raises(ValidationError):
        QuickStartRequest(patient_name="名" * 51, visit_type="outpatient")


def test_正常姓名与生僻长复姓不受影响():
    QuickStartRequest(patient_name="爱新觉罗·乌拉那拉氏", visit_type="outpatient")
    QuickStartRequest(patient_name="名" * 50, visit_type="outpatient")


def test_空姓名被拒():
    with pytest.raises(ValidationError):
        QuickStartRequest(patient_name="", visit_type="outpatient")


def test_病态超长正文被拒():
    with pytest.raises(ValidationError):
        AutoSaveDraftRequest(encounter_id="e", record_type="outpatient",
                             content="x" * 500_001)


def test_真实规模的长病历不受影响():
    """住院大病历几万字是真实存在的，上限必须宽松到碰不到它们。"""
    AutoSaveDraftRequest(encounter_id="e", record_type="outpatient",
                         content="病" * 100_000)


# ─── 服务层裸构造不再炸 500（收敛验证轮追根）───────────────────────────
#
# 500 字姓名 500 的真正根源在 _quick_start_inner 里的裸 PatientCreate(...)：
# 内部字段上限（address 500 / occupation 100 / …）齐全，但抛的是裸 pydantic
# ValidationError → catch-all → "服务器内部错误"。入口 QuickStartRequest 只拦
# 了姓名——address 等超长字段仍会穿进来。修法是在唯一构造点统一翻译成字段级
# 422（入口逐字段复制上限是第二真相源，必然漂移）。


@pytest.mark.asyncio
async def test_超长地址穿到服务层是422而不是500(async_db, monkeypatch):
    from types import SimpleNamespace

    from app.api.v1 import encounters_quickstart as q

    data = QuickStartRequest(
        patient_name="张三", visit_type="outpatient",
        address="地" * 501,      # 入口无校验、PatientCreate 上限 500
    )
    user = SimpleNamespace(id="doc-1", role="doctor", username="doc",
                           department_id=None, real_name="医生")
    # 只需要走到 PatientCreate 构造点；find 阶段对空库天然全 miss
    with pytest.raises(HTTPException) as ei:
        await q._quick_start_inner(data, async_db, user)
    assert ei.value.status_code == 422
    assert "address" in str(ei.value.detail), ei.value.detail
