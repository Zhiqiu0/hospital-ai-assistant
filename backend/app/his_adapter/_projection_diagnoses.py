"""正文诊断按显式标签拆分；编码只精确匹配冻结时条目，绝不猜诊断类别。"""
import re

from app.his_adapter._projection_parse import ProjectionError, value_of

_LABELS = {"西医诊断": "western", "中医疾病诊断": "tcm_disease",
           "中医证候诊断": "tcm_syndrome", "中医诊断": "tcm_merged"}


def parse_diagnoses(text: str) -> list[dict]:
    """仅分号、换行、编号分隔明确条目；逗号可能属于诊断名，不擅自拆开。"""
    if not value_of(text):
        return []
    output = []
    category = None
    for raw in re.split(r"\n|[；;]", text):
        raw = raw.strip()
        label = re.match(r"^(西医诊断|中医疾病诊断|中医证候诊断|中医诊断)[：:]\s*(.*)$", raw)
        if label:
            category, raw = _LABELS[label[1]], label[2]
        if re.search(r"(?:西医诊断|中医疾病诊断|中医证候诊断|中医诊断)[：:]", raw):
            raise ProjectionError("HIS回写失败：诊断类别标签未分行或分号分隔，存在歧义")
        # 数字序号仅在起始或已有分隔后处理，不截断名称里的分期数字。
        names = re.split(r"\s+(?=\d+[.、]\s*\D)", raw)
        for name in names:
            name = value_of(re.sub(r"^\d+[.、]\s*", "", name))
            if not name:
                continue
            if category == "tcm_merged":
                parts = re.split(r"\s+—\s+", name)
                if len(parts) > 2:
                    raise ProjectionError("HIS回写失败：中医诊断合并行格式有歧义")
                for index, part in enumerate(parts):
                    if value_of(part):
                        output.append({"name": part.strip(), "category": ("tcm_disease", "tcm_syndrome")[index]})
            else:
                item = {"name": name}
                if category:
                    item["category"] = category
                output.append(item)
    # 重复诊断会导致主诊断及编码对应关系含糊，不静默去重。
    identities = [(item.get("category"), item["name"]) for item in output]
    if len(set(identities)) != len(identities):
        raise ProjectionError("HIS回写失败：诊断条目重复，请核对正文")
    return output


def enrich_diagnoses(diagnoses: list[dict], candidates: list[dict]) -> list[dict]:
    """只带入同名且类别匹配的唯一候选编码；未匹配的新名称不继承旧代码。"""
    output = []
    for diagnosis in diagnoses:
        item = dict(diagnosis)
        matches = [candidate for candidate in candidates if candidate["name"].strip() == item["name"]
                   and ("category" not in item or candidate.get("category") == item["category"])]
        if len(matches) == 1:
            candidate = matches[0]
            for key in ("category", "code", "code_type", "is_primary", "admission_condition"):
                if key in candidate:
                    item[key] = candidate[key]
        # 无主诊断依据时不猜排序=主诊断；规范允许省略可选属性。
        output.append(item)
    # 主诊断先展示，其余保留医生条目的既有顺序；新名称仅附在末尾，不据排序猜主诊断。
    ranks = {(item.get("category"), item["name"]): index for index, item in enumerate(candidates)}
    return sorted(output, key=lambda item: (not item.get("is_primary", False),
        ranks.get((item.get("category"), item["name"]), len(ranks))))
