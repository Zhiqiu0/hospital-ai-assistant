"""严格分段与体征解析：不借用带启发式的质控解析器，不从自由叙述猜字段。"""
import re

from app.his_adapter._projection_templates import FOOTERS, TEMPLATES, TITLES, VITAL_FIELDS


class ProjectionError(ValueError):
    """可签发但不能安全逐字段回写；消息不含患者正文。"""


def value_of(text: str) -> str:
    """精确模板占位符转空串；“无/否认/暂无”仍是医生书写的有效值。"""
    text = text.strip()
    return "" if text in {"[未填写，需补充]", "[未填写,需补充]", "[未测]", "未记录"} else text


def split_labeled(text: str, labels: tuple[str, ...]) -> dict[str, str]:
    """只在行首切已知子标签，保留跨行内容并拒绝重复；未知前导内容不能丢弃。"""
    if not value_of(text):
        return {}
    pattern = re.compile(r"(?m)^[ \t]*(" + "|".join(map(re.escape, labels)) + r")[：:][ \t]*")
    matches = list(pattern.finditer(text))
    if not matches or value_of(text[:matches[0].start()]):
        raise ProjectionError("HIS回写失败：复合章节格式无法可靠识别，请核对规范字段标签")
    result = {}
    for i, match in enumerate(matches):
        label = match[1]
        if label in result:
            raise ProjectionError("HIS回写失败：复合章节包含重复字段")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        result[label] = value_of(text[match.end():end])
    return result


def split_sections(record_type: str, text: str) -> tuple[dict[str, str], str]:
    """识别十类规范正文及其页眉，返回章节和门急诊病发时间。"""
    if record_type not in TEMPLATES or not isinstance(text, str) or not text.strip():
        raise ProjectionError("HIS回写失败：文书类型或正文格式不受支持")
    template = TEMPLATES[record_type]
    flat = tuple(template) if record_type in {"course_record", "senior_round", "op_record"} else ()
    labels = flat + FOOTERS.get(record_type, ())
    extra = r"|^[ \t]*(?P<flat>" + "|".join(map(re.escape, labels)) + r")[：:][ \t]*" if labels else ""
    pattern = re.compile(r"^[ \t]*【(?P<bracket>[^】]+)】[ \t]*" + extra, re.M)
    matches = list(pattern.finditer(text))
    if not matches:
        raise ProjectionError("HIS回写失败：未识别规范文书章节")
    header = text[:matches[0].start()].strip()
    onset = ""
    if record_type in {"outpatient", "emergency"}:
        if header:
            match = re.fullmatch(r"就诊时间[：:]([^\n]*)[ \t\u3000]+病发时间[：:]([^\n]*)", header)
            if not match:
                raise ProjectionError("HIS回写失败：门急诊页眉格式无法识别")
            onset = value_of(match[2])
    elif header and header != TITLES.get(record_type):
        title = {"course_record": "病程记录", "senior_round": "上级医师查房记录", "post_op_record": "术后病程记录"}.get(record_type)
        # 只允许模板中的日期、时点、术后天数及查房医师行；不吞掉其他前导正文。
        first, *rest = header.splitlines()
        allowed = title and re.fullmatch(r"[\d_年月日时分 :：/\-]+" + title + r"(?:（术后第[\d_]+天）)?", first)
        if not allowed or len(rest) > 1 or (rest and not re.fullmatch(r"查房医师[：:][^\n]+", rest[0])):
            raise ProjectionError("HIS回写失败：住院文书页眉格式无法识别")
    result = {}
    for i, match in enumerate(matches):
        name = match.group("bracket") or match.group("flat")
        if name not in template and name not in FOOTERS.get(record_type, ()):
            raise ProjectionError("HIS回写失败：存在未支持的自定义章节")
        if name in result:
            raise ProjectionError("HIS回写失败：存在重复章节")
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        if "【" in body or "】" in body:
            raise ProjectionError("HIS回写失败：章节标记不完整或位置有歧义")
        result[name] = value_of(body)
    return result, onset


def parse_vitals(text: str) -> dict[str, str]:
    """完整消费规范体征行，缺失值先标空；输出层按协议省略空值，BP不会误认成P。"""
    result = dict.fromkeys(VITAL_FIELDS, "")
    if not value_of(text):
        return result
    patterns = {
        "T": ("temperature", r"℃|°C|度"), "P": ("pulse", r"次/分|次/min|bpm"),
        "R": ("respiration", r"次/分|次/min"), "SpO2": ("spo2", r"%"),
        "身高": ("height", r"cm"), "体重": ("weight", r"kg"),
    }
    token = re.compile(r"(T|P|R|BP|SpO2|身高|体重)[：:]\s*(\[未测\]|\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)([^\s]*)")
    seen = set()
    cursor = 0
    for match in token.finditer(text):
        if text[cursor:match.start()].strip():
            raise ProjectionError("HIS回写失败：生命体征含未识别内容")
        key, raw, unit = match.groups()
        if key in seen:
            raise ProjectionError("HIS回写失败：生命体征标签重复")
        seen.add(key)
        cursor = match.end()
        if raw == "[未测]":
            if unit:
                raise ProjectionError("HIS回写失败：生命体征占位格式不正确")
            continue
        if key == "BP":
            if not re.fullmatch(r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?", raw) or unit not in {"", "mmHg"}:
                raise ProjectionError("HIS回写失败：血压格式无法可靠拆分")
            result["bp_systolic"], result["bp_diastolic"] = [v.strip() for v in raw.split("/")]
        else:
            field, units = patterns[key]
            if "/" in raw or (unit and not re.fullmatch(units, unit)):
                raise ProjectionError("HIS回写失败：生命体征数值或单位无法识别")
            result[field] = raw
    if not seen or text[cursor:].strip():
        raise ProjectionError("HIS回写失败：生命体征格式无法识别")
    return result
