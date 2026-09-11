# -*- coding: utf-8 -*-
"""v1.5 增补说明的示例报文合同测试（2026-09-11）。

背景：增补文档白纸黑字写着"以下示例与我方回写实现逐字段一致"，而此前
builder 测试只覆盖了无编码的文本回落路径——这句对厂商的承诺没有任何测试
守着。按「规范里示例错比正文错更致命」的教训（厂商照示例做不看正文），
这里把增补第三节示例场景一比一造出来，diagnoses[] 逐字段断言：

  · 西医主诊断：is_primary=true + ICD10 码 + 入院病情"有"
  · 西医合并症：is_primary=false + ICD10 码 + 入院病情"临床未确定"
  · 中医疾病：  TCD_DIS 存储 → 下发 code_type="GB95"（A 码）
  · 中医证候：  TCD_SYN 存储 → 下发 code_type="GB95"（B 码），无入院病情则缺省

任何一处实现与示例漂移，本测试当场红——发给厂商的承诺由 CI 守着。
"""
from datetime import date

import pytest

from app.his_adapter.writeback_builder import build_writeback_payload
from app.models.encounter import Diagnosis, Encounter, InquiryInput
from app.models.patient import Patient


@pytest.mark.asyncio
async def test_v15示例报文与实现逐字段一致(async_db):
    p = Patient(name="示例患者", birth_date=date(1970, 1, 1))
    async_db.add(p)
    await async_db.commit()
    enc = Encounter(
        patient_id=p.id, doctor_id="doc-1", visit_type="inpatient",
        visit_no="MZ20260821001", status="in_progress",
        his_external_ref={"his_brand": "jinsuanpan", "hospital_code": "H1",
                          "his_visit_no": "MZ20260821001", "doctor_code": "D001"},
    )
    async_db.add(enc)
    await async_db.commit()
    async_db.add(InquiryInput(encounter_id=enc.id, version=1,
                              chief_complaint="头晕伴血压升高"))
    # 与增补示例一比一的四条诊断（sort_order 即展示序，主诊断在前）
    async_db.add_all([
        Diagnosis(encounter_id=enc.id, name="原发性高血压", category="western",
                  is_primary=True, sort_order=0, admission_condition="有",
                  code="I10.x09", code_type="ICD10"),
        Diagnosis(encounter_id=enc.id, name="2型糖尿病", category="western",
                  is_primary=False, sort_order=1, admission_condition="临床未确定",
                  code="E11.900", code_type="ICD10"),
        Diagnosis(encounter_id=enc.id, name="眩晕", category="tcm_disease",
                  is_primary=False, sort_order=2, admission_condition="有",
                  code="A17.07", code_type="TCD_DIS"),
        Diagnosis(encounter_id=enc.id, name="肝阳上亢证", category="tcm_syndrome",
                  is_primary=False, sort_order=3,
                  code="B04.02.01.04.02.01", code_type="TCD_SYN"),
    ])
    await async_db.commit()

    payload = await build_writeback_payload(async_db, enc.id, app_version="1.0.0")

    # ——逐字段对齐增补第三节示例——
    assert payload["diagnoses"] == [
        {"name": "原发性高血压", "is_primary": True, "category": "western",
         "admission_condition": "有", "code": "I10.x09", "code_type": "ICD10"},
        {"name": "2型糖尿病", "is_primary": False, "category": "western",
         "admission_condition": "临床未确定", "code": "E11.900", "code_type": "ICD10"},
        {"name": "眩晕", "is_primary": False, "category": "tcm_disease",
         "admission_condition": "有", "code": "A17.07", "code_type": "GB95"},
        {"name": "肝阳上亢证", "is_primary": False, "category": "tcm_syndrome",
         "code": "B04.02.01.04.02.01", "code_type": "GB95"},
    ], "diagnoses[] 与 v1.5 增补示例漂移——发给厂商的示例即承诺，改实现必须同步改文档"

    # 增补正文的三条硬承诺
    primaries = [d for d in payload["diagnoses"] if d["is_primary"]]
    assert len(primaries) == 1, "全数组恰一条 is_primary=true（增补第二节承诺）"
    assert payload["diagnoses"][0]["is_primary"], "主诊断在前的展示序（增补第二节承诺）"
    assert payload["visit_id"] == "MZ20260821001"
