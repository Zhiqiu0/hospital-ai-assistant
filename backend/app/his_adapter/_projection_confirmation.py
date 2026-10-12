"""签发及修订共用的显式诊断确认校验；不信任预览结果或客户端编码。"""
from collections import Counter

from fastapi import HTTPException
from pydantic import ValidationError

from app.his_adapter._projection_diagnoses import enrich_diagnoses
from app.schemas.diagnosis_confirmation import ConfirmedDiagnosis


def confirm_diagnoses(parsed: list[dict], candidates: list[dict], confirmation: list) -> list[dict]:
    """重新核对本次正文完整诊断集合；确认只能修改主诊断标记，不可增删或改类别。"""
    try:
        confirmed = [ConfirmedDiagnosis.model_validate(item).model_dump() for item in confirmation]
    except (ValidationError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="诊断确认格式无效，只能提交名称、类别及布尔主诊断标记") from exc
    enriched = enrich_diagnoses(parsed, candidates)
    def identity(item):
        """名称和类别共同确定诊断身份，不能只比较显示名称。"""
        return (item["name"], item.get("category"))
    expected = Counter(identity(item) for item in enriched)
    actual = Counter(identity(item) for item in confirmed)
    if expected != actual or any(count != 1 for count in actual.values()):
        raise HTTPException(status_code=422, detail="诊断确认与当前正文不一致，请重新核对完整诊断列表")
    if confirmed and sum(item["is_primary"] for item in confirmed) != 1:
        raise HTTPException(status_code=422, detail="请明确选择且仅选择一个主诊断")
    primary = {identity(item): item["is_primary"] for item in confirmed}
    for item in enriched:
        item["is_primary"] = primary[identity(item)]
    # 仅根据已确认标记稳定前置，编码仍来自唯一同名候选，改名不继承旧编码。
    return sorted(enriched, key=lambda item: not item["is_primary"])


def assert_signed_confirmation_matches(content: dict, confirmation: list) -> None:
    """重复签发只允许同样确认；不能用幂等返回偷偷忽略不同的主诊断选择。"""
    from app.his_adapter.record_projection import project_record
    from app.his_adapter._projection_parse import ProjectionError
    projection = content.get("his_projection") or {}
    try:
        parsed = project_record(projection.get("record_type", "outpatient"), content.get("text", ""))
    except ProjectionError as exc:
        raise HTTPException(status_code=422, detail="正文格式无法识别，不能确认诊断") from exc
    confirmed = confirm_diagnoses(parsed["diagnoses"], projection.get("diagnosis_basis", projection.get("diagnoses", [])), confirmation)
    def choices(items):
        """忽略展示顺序，但完整比较诊断身份及主诊断选择。"""
        return {(item["name"], item.get("category"), item.get("is_primary", False)) for item in items}
    if "error" in projection or choices(confirmed) != choices(projection.get("diagnoses", [])):
        raise HTTPException(status_code=409, detail="病历已签发，修改主诊断须通过管理员修订通道")
