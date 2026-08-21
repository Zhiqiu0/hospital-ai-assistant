# -*- coding: utf-8 -*-
"""诊断条目→文本投影 契约对拍测试（2026-08-21 阶段1b）。

用例表 shared/contracts/diagnosis_projection_cases.json——前端
diagnosisProjection.test.ts 读同一份。后端投影是权威（PUT 后落库）。
"""
import json
from pathlib import Path

import pytest

from app.schemas.diagnosis import DiagnosisItemIn
from app.services.diagnosis_service import render_diagnosis_projection

_CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "contracts" / "diagnosis_projection_cases.json")
    .read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["note"])
def test_projection_contract(case):
    items = [DiagnosisItemIn(**e) for e in case["entries"]]
    proj = render_diagnosis_projection(items)
    for key in ("western_diagnosis", "tcm_disease_diagnosis",
                "tcm_syndrome_diagnosis", "admission_diagnosis"):
        assert proj[key] == case[key], f"{case['note']}: {key} 不符"
