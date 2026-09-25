"""模型输出的业务结构边界：JSON 可解析不等于业务结果有效。"""
from app.services.ai.record_schemas import SCHEMA_MAP, PLACEHOLDER


class AIOutputContractError(ValueError):
    """格式异常可有限重试，文案不包含患者数据。"""

    user_message = "AI 返回的内容结构不完整，请重试"


def validate_record_output(result: object, record_type: str) -> dict:
    """要求完整模板键及文本值；空值兼容未录入项，拒绝整份空病历。"""
    schema = SCHEMA_MAP[record_type]
    if not isinstance(result, dict) or not schema.keys() <= result.keys():
        raise AIOutputContractError("病历结构缺少模板字段")
    values = [result[key] for key in schema]
    if any(value is not None and not isinstance(value, str) for value in values):
        raise AIOutputContractError("病历字段必须为文本或空值")
    if not any(value and value.strip() not in ("", PLACEHOLDER) for value in values):
        raise AIOutputContractError("病历没有可用内容")
    # 模型偶发的附加元数据不参与渲染，保持旧客户端兼容。
    return result


def require_list_field(result: object, field: str) -> list:
    """显式空列表合法；缺键、null、对象不能伪装成零条结果。"""
    if not isinstance(result, dict) or not isinstance(result.get(field), list):
        raise AIOutputContractError(f"AI 输出缺少有效 {field} 列表")
    return result[field]


def require_text_items(result: object, field: str, text_fields: tuple[str, ...]) -> list:
    """逐条检查消费端必需的文本键；显式空文本仍由现有业务过滤逻辑处理。"""
    items = require_list_field(result, field)
    if any(not isinstance(item, dict) or any(
            not isinstance(item.get(key), str) for key in text_fields) for item in items):
        raise AIOutputContractError(f"AI 输出 {field} 条目缺少有效文本字段")
    return items


def validate_voice_output(result: object) -> None:
    """语音允许显式空提取，但必须返回摘要、对话和问诊三个正确类型的容器。"""
    if (not isinstance(result, dict)
            or not isinstance(result.get("transcript_summary"), str)
            or not isinstance(result.get("inquiry"), dict)):
        raise AIOutputContractError("语音结构缺少有效摘要或问诊对象")
    dialogue = require_list_field(result, "speaker_dialogue")
    if any(not isinstance(item, dict)
           or item.get("speaker") not in ("doctor", "patient", "uncertain")
           or not isinstance(item.get("text"), str) for item in dialogue):
        raise AIOutputContractError("语音对话条目结构无效")
    for key, value in result["inquiry"].items():
        if key == "vital_signs":
            # 保留既有数值转文本及无出处剔除逻辑，禁止嵌套数组/对象溜入表单。
            if value is not None and (not isinstance(value, dict) or any(
                    item is not None and (isinstance(item, bool)
                    or not isinstance(item, (str, int, float))) for item in value.values())):
                raise AIOutputContractError("语音生命体征结构无效")
        elif value is not None and (isinstance(value, bool)
                                   or not isinstance(value, (str, int, float))):
            raise AIOutputContractError("语音问诊字段必须是文本或数值")
