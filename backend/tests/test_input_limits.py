# -*- coding: utf-8 -*-
"""超长输入边界（2026-09-10 收敛验证轮 · 角度 D）。

生产实测两条实锤：直连 API 传 500 字姓名 → 穿过校验直插 String(50) 列、
DataError 炸 500（HIS 入站早按列宽截断，直连这条漏了——同一红线要覆盖所有
入口）；5MB 病历正文一路 200 落库，而每次编辑/签发都把全文整份复制进
record_versions。修法：姓名按列宽 422 拒绝（不截断——医生主动录入的身份字段
静默截掉会造出错名字的档案），正文 50 万字符上限（宽松到不可能误伤真病历）。
"""
import pytest
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
