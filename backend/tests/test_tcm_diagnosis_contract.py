# -*- coding: utf-8 -*-
"""中医诊断合并行 拆/合 契约对拍测试（2026-08-21 阶段0 收口）。

用例表在 shared/contracts/tcm_diagnosis_cases.json——前端
frontend/src/domain/medical/tcmDiagnosis.test.ts 读同一份文件。
改契约只改 JSON，哪端实现没跟上哪端的 CI 红；单方面改实现不改 JSON 也红。
"""
import json
from pathlib import Path

import pytest

from app.services.ai._render_common import _merge_tcm_diagnosis
from app.services.qc_engine.parser import _split_tcm_diagnosis

_CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "shared" / "contracts" / "tcm_diagnosis_cases.json")
    .read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CASES["split_cases"], ids=lambda c: c["note"])
def test_split_contract(case):
    disease, syndrome = _split_tcm_diagnosis(case["input"])
    assert disease == case["disease"], f"疾病位不符：{case['input']!r}"
    assert syndrome == case["syndrome"], f"证候位不符：{case['input']!r}"


@pytest.mark.parametrize("case", _CASES["merge_cases"], ids=lambda c: c["note"])
def test_merge_contract(case):
    assert _merge_tcm_diagnosis(case["disease"], case["syndrome"]) == case["merged"]
