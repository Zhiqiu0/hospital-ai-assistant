# -*- coding: utf-8 -*-
"""病案首页数据预取 + 诊断一致性提示（services/ai/_qc_frontpage.py，2026-08-21 阶段3）。

  - load_front_page      : 按 encounter_id 预取首页结构化数据 → FrontPageData
                           （qc_engine 保持纯函数，DB 访问收口在本 service 层——
                           355 个既有 rubric 测试因此零改动）
  - check_diagnosis_hints: 出院诊断完整性交叉检查（提示级，不进法定评分）

设计边界：提示级检查不属于 PDF 评分条款，绝不扣分——以 issue(提示) 形式
附加在质控结果里，医生自行判断。这与"法定标准为纲、AI 不越权"一致。
"""
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Diagnosis, Encounter
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.patient import Patient
from app.services.qc_engine.checker import FrontPageData

logger = logging.getLogger(__name__)


async def load_front_page(db: AsyncSession, encounter_id: str | None) -> FrontPageData:
    """预取病案首页结构化数据；无 encounter 上下文返回未加载态（规则全跳过）。"""
    if not encounter_id:
        return FrontPageData()
    enc = await db.get(Encounter, encounter_id)
    if enc is None:
        return FrontPageData()
    patient = await db.get(Patient, enc.patient_id) if enc.patient_id else None
    dx_rows = (await db.execute(
        select(Diagnosis)
        .where(Diagnosis.encounter_id == encounter_id)
        .order_by(Diagnosis.is_primary.desc(), Diagnosis.sort_order)
    )).scalars().all()
    return FrontPageData(
        id_card=(patient.id_card or "") if patient else "",
        birth_date=str(patient.birth_date or "") if patient else "",
        gender=(patient.gender or "") if patient else "",
        blood_type=(patient.blood_type or "") if patient else "",
        admission_route=enc.admission_route or "",
        allergy_history=(getattr(patient, "profile_allergy_history", None) or "") if patient else "",
        diagnoses=tuple(
            {
                "category": d.category,
                "name": d.name,
                "code": d.code,
                "is_primary": d.is_primary,
                "admission_condition": d.admission_condition,
            }
            for d in dx_rows
        ),
        loaded=True,
    )


# 诊断章节行的前缀噪音（提取名字用）
_DIAG_LINE_PREFIX = re.compile(r"^(中医诊断|西医诊断|入院诊断|出院诊断)[：:]\s*|^\d+[.、]\s*")
_DIAG_SECTIONS = ("诊断", "入院诊断", "出院诊断", "初步诊断")


def _extract_diagnosis_names(record_text: str) -> set[str]:
    """从一份文书正文的诊断类章节提取诊断名集合（确定性解析，不用 LLM）。"""
    from app.services.qc_engine.parser import _split_tcm_diagnosis, parse_record

    names: set[str] = set()
    sections = parse_record(record_text)
    for sec_name in _DIAG_SECTIONS:
        sec = sections.get(sec_name)
        if sec is None or not sec.is_filled():
            continue
        for raw in sec.raw_value.split("\n"):
            line = _DIAG_LINE_PREFIX.sub("", raw.strip())
            if not line or line.startswith("["):
                continue
            # 合并行拆开（"眩晕病 — 肝阳上亢证"两半都算）；分号串再拆
            for part in re.split(r"[；;]", line):
                part = _DIAG_LINE_PREFIX.sub("", part.strip())
                if not part:
                    continue
                disease, syndrome = _split_tcm_diagnosis(part)
                for n in (disease, syndrome):
                    n = n.strip()
                    if n and len(n) >= 2:
                        names.add(n)
    return names


async def check_diagnosis_hints(
    db: AsyncSession, encounter_id: str | None, record_type: str | None,
    current_diagnoses: tuple,
) -> list[dict]:
    """出院诊断完整性交叉检查（提示级）。

    场景：写出院记录时，把**本次住院已签发文书**（入院记录/病程）诊断章节里
    出现过、但当前诊断条目里没有的诊断名列出来提示——合并症漏填是 DRG 分组
    偏差的第一大原因（病案首页质控方案 DRG 关联一节的"高编流失"线索）。
    只做确定性文本解析比对，不用 LLM，不扣分。
    """
    if not encounter_id or record_type != "discharge_record":
        return []
    current_names = {d.get("name", "").strip() for d in current_diagnoses}
    if not current_names:
        return []  # 条目为空走法定 veto（主诊断缺失），这里不重复报

    rows = (await db.execute(
        select(RecordVersion.content)
        .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
        .where(
            MedicalRecord.encounter_id == encounter_id,
            MedicalRecord.status == "submitted",
            RecordVersion.version_no == MedicalRecord.current_version,
        )
    )).scalars().all()
    seen: set[str] = set()
    for content in rows:
        text = content.get("text", "") if isinstance(content, dict) else (content or "")
        seen |= _extract_diagnosis_names(text)

    # 差集：此前文书写过、当前条目没有（子串互含视为同一诊断，防"高血压病/高血压"误报）
    missing = sorted(
        n for n in seen
        if not any(n in c or c in n for c in current_names)
    )
    if not missing:
        return []
    return [{
        "risk_level": "medium",
        "field_name": "出院诊断",
        "item_name": "病案首页",
        "issue_description": (
            f"住院期间文书曾出现以下诊断，但当前诊断条目未包含："
            f"{('、'.join(missing[:8]))}{'…' if len(missing) > 8 else ''}。"
            "请核对是否漏填合并症/并发症（漏填其他诊断是 DRG 分组偏差的首要原因）"
        ),
        "suggestion": "如属实请在诊断条目中补录；如已治愈剔除属正常，忽略本提示即可",
        "score_impact": "提示",
        "source": "rule",
        "issue_type": "frontpage_hint",
    }]
