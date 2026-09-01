"""接诊快照序列化纯函数（services/encounter_serializers.py）

从 encounter_service 拆出（Round: 超标文件拆分）。都是无副作用的
ORM → dict 转换，供 EncounterSnapshotMixin 组装工作台快照时复用。
"""
from typing import Any, Optional

from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion
from app.models.voice_record import VoiceRecord
from app.schemas.encounter import InquirySnapshot
from app.services.record_time import describe_record_time

# 病历内容字段标签（结构化 dict 内容回传前端时按此顺序拼成可读文本）
_RECORD_CONTENT_LABELS = {
    "chief_complaint": "主诉",
    "history_present_illness": "现病史",
    "past_history": "既往史",
    "allergy_history": "过敏史",
    "personal_history": "个人史",
    "physical_exam": "体格检查",
    "auxiliary_exam": "辅助检查",
    "initial_diagnosis": "初步诊断",
    "admission_diagnosis": "入院诊断",
    "treatment_plan": "诊疗计划",
}


def _parse_record_content(content: Any) -> str:
    """将 RecordVersion.content 三种存储形态统一序列化为可读文本。

    支持：
      - quick_save 格式：{"text": "病历全文"} → 直接取 text
      - 结构化格式：{"chief_complaint": ..., ...} → 按字段顺序拼成可读段落
      - 纯字符串：原样返回
      - None 或其他：返回空字符串
    """
    if isinstance(content, dict):
        if "text" in content:
            return content["text"] or ""
        parts: list[str] = []
        for key, label in _RECORD_CONTENT_LABELS.items():
            val = content.get(key, "")
            if val:
                parts.append(f"【{label}】\n{val}")
        # 映射之外的字段追加到末尾，避免新增字段静默丢失
        for key, val in content.items():
            if key not in _RECORD_CONTENT_LABELS and val:
                parts.append(f"【{key}】\n{val}")
        return "\n\n".join(parts)
    if isinstance(content, str):
        return content
    return ""


def _serialize_record(
    record: MedicalRecord,
    version: Optional[RecordVersion],
    *,
    discharged_at=None,
    visit_type: Optional[str] = None,
) -> dict:
    """单条病历 → 工作台快照里的字典。

    discharged_at / visit_type 供补记判定用：住院患者出院之后才落笔的文书
    （出院记录除外）按定义就是补记，见 record_time.is_late_entry。
    """
    return {
        "record_id": record.id,
        "record_type": record.record_type,
        "status": record.status,
        "current_version": record.current_version,
        # record_no：住院同类型多份文书的序号，前端时间轴要靠它区分显示
        "record_no": getattr(record, "record_no", None),
        "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
        # created_at 必须返回（2026-08-14 第八轮审计）：前端时间轴用
        # submitted_at || created_at 排序，未签发草稿 submitted_at 为 null，
        # 原先后端不返回 created_at → recordedAt 为空串 → 按 0 排序，
        # 草稿一律排到入院记录之前的时间轴最顶端且不显示日期。
        "created_at": record.created_at.isoformat() if record.created_at else None,
        # 记录时间三元组（第八轮审计后按行业标准）：临床相关时间 / 系统录入时间 /
        # 是否补记。补记必须让前端看得见——见 services/record_time.py 的规范依据。
        **describe_record_time(
            record.recorded_at, record.created_at,
            discharged_at=discharged_at,
            record_type=record.record_type,
            visit_type=visit_type,
        ),
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "content": _parse_record_content(version.content if version else None),
        # 病案首页快照：签发瞬间冻结的患者完整身份 + 接诊信息。
        # 未签发病历此字段为 None，前端 fallback 到当前 patient 数据。
        "patient_snapshot": record.patient_snapshot,
    }


def _serialize_inquiry(inquiry: Optional[InquiryInput], encounter: Encounter) -> Optional[dict]:
    """问诊 ORM → 工作台快照字段字典。

    用 Pydantic 自动 None → ""（取代原 40+ 行手工 `or ""`）。
    visit_time 缺省时回退到 encounter.visited_at，便于首次生成病历时有时间戳。
    """
    if inquiry is None:
        return None
    data = InquirySnapshot.model_validate(inquiry).model_dump()
    if not data["visit_time"] and encounter.visited_at:
        data["visit_time"] = encounter.visited_at.strftime("%Y-%m-%d %H:%M")
    return data


def _serialize_voice(voice: Optional[VoiceRecord]) -> Optional[dict]:
    """最新一条语音录音 → 字典。"""
    if voice is None:
        return None
    return {
        "id": voice.id,
        "status": voice.status,
        "raw_transcript": voice.raw_transcript or "",
        "transcript_summary": voice.transcript_summary or "",
        "speaker_dialogue": voice.get_speaker_dialogue(),
        "draft_record": voice.draft_record or "",
    }
