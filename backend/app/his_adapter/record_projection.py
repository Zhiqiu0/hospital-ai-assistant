"""将最终正文投影为 v1.4 字段并冻结到版本；失败保存原因，不阻断自由文本签发。"""
import re
from copy import deepcopy

from sqlalchemy import select

from app.his_adapter._projection_diagnoses import enrich_diagnoses, parse_diagnoses
from app.his_adapter._projection_parse import ProjectionError, parse_vitals, split_labeled, split_sections, value_of
from app.his_adapter._projection_templates import TEMPLATES, VISIT_FIELDS, VITAL_FIELDS

_EXAM = {"望诊": "tcm_inspection", "闻诊": "tcm_auscultation", "切诊·舌象": "tongue_coating",
         "切诊·脉象": "pulse_condition", "其余阳性体征": "physical_exam", "重点体征": "physical_exam"}
_TREATMENT = {"治则治法": "treatment_method", "处理意见": "treatment_plan",
              "复诊建议": "followup_advice", "注意事项": "precautions"}
_ASSESSMENT = ("· 疼痛评估（NRS评分）", "· VTE风险", "· 营养风险", "· 心理状态",
               "· 康复需求", "· 当前用药", "· 宗教信仰/饮食禁忌")


def _validate_primary(projection: dict) -> None:
    """v1.5非空诊断数组必须恰有一个医生明确选择的主诊断，不以排序猜测。"""
    diagnoses = projection["diagnoses"]
    if diagnoses and sum(item.get("is_primary") is True for item in diagnoses) != 1:
        raise ProjectionError("HIS回写失败：正文诊断与签发时明确选择的主诊断不一致，需核对并确认后修订")
    for item in diagnoses:
        item.setdefault("is_primary", False)


def _exam_fields(body: str, record: dict, vitals: dict, record_type: str) -> None:
    """体征独立解析；门急诊的普通体检与四诊按模板标签分离。"""
    if not value_of(body):
        return
    lines = body.splitlines()
    # 模板体征固定在首行，所有值从该行读取，禁止遍历任意叙述捞数字。
    first = lines[0].strip()
    if first.startswith(("T:", "T：", "P:", "P：", "BP:", "BP：", "R:", "R：", "SpO2:", "SpO₂:", "身高:", "体重:")):
        vitals.update(parse_vitals(first))
        lines = lines[1:]
    elif not value_of(first):
        lines = lines[1:]
    rest = "\n".join(lines).strip()
    if record_type == "admission_note":
        record["physical_exam"] = value_of(rest)
    elif value_of(rest):
        # 标签行之前的无标签文字归入体格检查正文（physical_exam）。质控建议「写入病历」、医生
        # 手写查体都会在【体格检查】里留下这样的自由文本；它本来就是体检内容，归入通用体检
        # 字段不算猜字段。此前一律判失败，这类病历在 HIS 来源接诊里签不了（2026-11-27 体检）。
        first_label = re.search(r"(?m)^[ \t]*(?:" + "|".join(map(re.escape, _EXAM)) + r")[：:]", rest)
        lead = value_of(rest[:first_label.start()] if first_label else rest)
        parts = split_labeled(rest[first_label.start():], tuple(_EXAM)) if first_label else {}
        used = set()
        for label, value in parts.items():
            field = _EXAM[label]
            if field in used:
                raise ProjectionError("HIS回写失败：普通体检包含多个同义标签")
            used.add(field)
            record[field] = value
        if lead:
            record["physical_exam"] = "\n".join(v for v in (lead, record.get("physical_exam", "")) if v)


def project_record(record_type: str, text: str) -> dict:
    """纯确定性投影；已知全文专属段落仍留在full_text，不添加厂商私有字段。"""
    sections, onset = split_sections(record_type, text)
    template = TEMPLATES[record_type]
    if record_type in {"outpatient", "emergency"}:
        record = dict.fromkeys(VISIT_FIELDS, "")
        record["onset_time"] = onset
    else:
        record = dict.fromkeys((field for field in template.values() if field and not field.startswith("@")), "")
    vitals = dict.fromkeys(VITAL_FIELDS, "") if "@exam" in template.values() else {}
    if "@exam" in template.values():
        record["physical_exam"] = ""
    if "@assessment" in template.values():
        record["current_medications"] = ""
    diagnoses = []
    used_fields = set()
    for name, body in sections.items():
        field = template.get(name)
        if field is None:
            continue  # 已通过白名单识别，既有协议未覆盖的字段仅全文存档。
        # 复合节与独立节也可能指向同一字段，按目标字段检测重复而非只看标题。
        targets = {field}
        if field == "@assessment":
            targets = {"current_medications"}
        elif field == "@exam":
            targets = set(_EXAM.values())
        elif field == "@treatment":
            targets = set(_TREATMENT.values())
        if used_fields & targets:
            raise ProjectionError("HIS回写失败：同义章节重复映射到相同字段")
        used_fields.update(targets)
        if field == "@exam":
            _exam_fields(body, record, vitals, record_type)
        elif field == "@diagnoses":
            diagnoses = parse_diagnoses(body)
        elif field == "@treatment":
            for label, value in split_labeled(body, tuple(_TREATMENT)).items():
                record[_TREATMENT[label]] = value
        elif field == "@assessment":
            record["current_medications"] = split_labeled(body, _ASSESSMENT).get("· 当前用药", "")
        else:
            record[field] = body
    is_tcm = any(record.get(field) for field in ("tcm_inspection", "tcm_auscultation", "tongue_coating", "pulse_condition"))
    is_tcm |= any(item.get("category", "").startswith("tcm_") for item in diagnoses)
    # v1.4体征特别条款：未测/删除的体征缺省，不发清空指令；正文record字段仍保留空串。
    return {"schema_version": 1, "record_type": record_type, "record": record,
            "vitals": {key: value for key, value in vitals.items() if value},
            "diagnoses": diagnoses, "is_tcm": bool(is_tcm)}


async def load_diagnosis_basis(db, encounter_id: str | None, previous_projection: dict | None = None) -> list[dict]:
    """首签取当前明确条目；修订只取历史快照，quickstart无接诊不查询任何患者资料。"""
    if previous_projection is not None:
        return deepcopy(previous_projection.get("diagnosis_basis", previous_projection.get("diagnoses", [])))
    if not encounter_id:
        return []
    from app.models.encounter import Diagnosis
    rows = (await db.execute(select(Diagnosis).where(Diagnosis.encounter_id == encounter_id)
                            .order_by(Diagnosis.sort_order, Diagnosis.created_at)
                            .execution_options(populate_existing=True))).scalars().all()
    candidates = []
    for row in rows:
        candidate = {"name": row.name, "category": row.category, "is_primary": row.is_primary}
        if row.code:
            candidate["code"] = row.code
            code_type = {"ICD10": "ICD10", "TCD_DIS": "GB95", "TCD_SYN": "GB95"}.get(row.code_type)
            if code_type:
                candidate["code_type"] = code_type
        if row.admission_condition:
            candidate["admission_condition"] = row.admission_condition
        candidates.append(candidate)
    return candidates


async def add_dictionary_candidates(db, parsed: list[dict], candidates: list[dict]) -> list[dict]:
    """首签时给「正文里有、条目里没有」的诊断按字典补编码候选，返回新列表不改入参。

    背景（2026-11-27 联调实测）：编码原先只来自问诊表单保存的诊断条目；病历生成后
    医生从诊断建议写入、或直接在正文里写的诊断没有对应条目，回写时全部无编码。
    规则与保存诊断条目时的自动补码一致，仍是确定性匹配、不猜：
      · 只处理正文里带明确类别标签的诊断（西医/中医疾病/中医证候），无标签的不补；
      · 名称与该类别对应字典的条目完全相同，且恰好命中一个编码才补；
      · 已有同名同类别条目的不动（医生选过的编码优先，哪怕它没有编码）。
    """
    from app.models.encounter import DiagnosisCode
    from app.services.diagnosis_service import CATEGORY_TO_CODE_TYPE

    known = {(item["name"].strip(), item.get("category")) for item in candidates}
    pending = [item for item in parsed if item.get("category") in CATEGORY_TO_CODE_TYPE
               and (item["name"], item["category"]) not in known]
    if not pending:
        return candidates
    rows = (await db.execute(
        select(DiagnosisCode.code, DiagnosisCode.name, DiagnosisCode.code_type)
        .where(DiagnosisCode.name.in_({item["name"] for item in pending}))
    )).all()
    codes: dict[tuple[str, str], list[str]] = {}
    for code, name, code_type in rows:
        codes.setdefault((code_type, name), []).append(code)
    extra = []
    for item in pending:
        dict_type = CATEGORY_TO_CODE_TYPE[item["category"]]
        matched = codes.get((dict_type, item["name"]), [])
        if len(matched) == 1:
            # 回写协议的编码体系口径：中医病/证统一为 GB95（与 load_diagnosis_basis 一致）。
            extra.append({"name": item["name"], "category": item["category"], "code": matched[0],
                          "code_type": "ICD10" if dict_type == "ICD10" else "GB95"})
    return candidates + extra


async def freeze_record_projection(db, encounter_id: str, record_type: str, content: str,
                                   previous_projection: dict | None = None,
                                   confirmed_diagnoses: list | None = None) -> dict:
    """签发时冻结体征和诊断编码；错误确认拒绝提交，未提供确认时保留安全失败状态。"""
    candidates = await load_diagnosis_basis(db, encounter_id, previous_projection)
    # 即使正文格式暂时错误，也冻结当时明确选择的候选供后续同名修订匹配。
    # basis仅是签发依据，不属于可发送diagnoses；失败依然禁止回写。
    basis = {"schema_version": 1, "record_type": record_type, "diagnosis_basis": deepcopy(candidates)}
    try:
        projection = project_record(record_type, content)
        if previous_projection is None and encounter_id:
            # 仅首签补字典候选；修订沿用历史快照，不拿今天的字典追补历史编码。
            candidates = await add_dictionary_candidates(db, projection["diagnoses"], candidates)
            basis["diagnosis_basis"] = deepcopy(candidates)
        if confirmed_diagnoses is not None:
            # 服务端重新解析本次正文，不能仅相信之前预览或空列表的真假值。
            from app.his_adapter._projection_confirmation import confirm_diagnoses
            projection["diagnoses"] = confirm_diagnoses(projection["diagnoses"], candidates, confirmed_diagnoses)
            basis["diagnosis_basis"] = deepcopy(projection["diagnoses"])
        else:
            projection["diagnoses"] = enrich_diagnoses(projection["diagnoses"], candidates)
        _validate_primary(projection)
    except ProjectionError as exc:
        if confirmed_diagnoses is not None:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail="正文无法可靠解析，请修正格式后重新核对诊断") from exc
        return {**basis, "error": str(exc)}
    projection["diagnosis_basis"] = basis["diagnosis_basis"]
    projection["is_tcm"] |= any(item.get("category", "").startswith("tcm_") for item in projection["diagnoses"])
    return projection


def projection_for_writeback(content, record_type: str) -> dict:
    """重试只读版本投影；旧版本仅反解正文，不从今天的接诊数据追补历史编码。"""
    if isinstance(content, dict) and "his_projection" in content:
        projection = content["his_projection"]
        if not isinstance(projection, dict) or projection.get("schema_version") != 1 or projection.get("record_type") != record_type:
            raise ProjectionError("HIS回写失败：版本投影格式不受支持")
        if projection.get("error"):
            raise ProjectionError(projection["error"])
        _validate_primary(projection)
        return deepcopy(projection)
    text = content.get("text", "") if isinstance(content, dict) else content
    projection = project_record(record_type, text)
    _validate_primary(projection)
    return projection
