"""病历电子签名防篡改哈希链（services/_record_signature.py）

2026-08-11 病历可信——分级评审电子签名项的前置基线。

问题：原先"签发"只把 medical_records.status 改成 submitted，任何有库权限的人
直接改一版已签发病历的正文，系统毫无察觉——法律上等同未签名，评审现场判不过。

方案：签发时对 (正文 + 患者快照 + 医生 + 签发时间 + 上一份签发病历的哈希) 算
SHA-256，存进 record_versions.sign_hash；prev_hash 指向链上前一环。任何对已签发
正文/快照的回改、或删除一条签发记录，都会让 recompute 出的哈希对不上、链断裂。

这不替代医院 CA/UKey 的数字签名（那需对接医院 CA），是其前置基线：先保证
"改动可发现"，再谈"不可抵赖"。
"""
import hashlib
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medical_record import RecordVersion

# 签发链的创世哈希（第一份签发病历的 prev_hash）
GENESIS_HASH = "0" * 64


def compute_sign_hash(
    *,
    content_text: str,
    patient_snapshot: Optional[dict],
    doctor_id: str,
    submitted_at_iso: str,
    prev_hash: str,
) -> str:
    """按规范化 payload 算 SHA-256。字段顺序固定 + JSON sort_keys，保证可复算一致。"""
    payload = json.dumps(
        {
            "content": content_text or "",
            "snapshot": patient_snapshot or {},
            "doctor_id": doctor_id or "",
            "submitted_at": submitted_at_iso or "",
            "prev_hash": prev_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def latest_chain_hash(db: AsyncSession) -> str:
    """取链尾（最近一份签发病历的 sign_hash）作为新签发的 prev_hash。

    并发两份签发可能读到同一 prev_hash 形成分叉——首版可接受（两环都是合法内容哈希，
    分叉不影响"内容被改可发现"这一核心保护）；后续要强串行可加库级 advisory lock。
    """
    row = (await db.execute(
        select(RecordVersion.sign_hash)
        .where(RecordVersion.sign_hash.isnot(None))
        .order_by(RecordVersion.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return row or GENESIS_HASH


def content_text_of(version_content) -> str:
    """从 RecordVersion.content（{"text": ...} 或 {"content": ...}）取纯文本正文。"""
    if isinstance(version_content, dict):
        return version_content.get("text") or version_content.get("content") or ""
    return str(version_content or "")


async def verify_version(db: AsyncSession, version: RecordVersion) -> bool:
    """复算某签发版本的哈希并比对 → True=未被篡改。无 sign_hash 的返回 True（非签发版本不校验）。"""
    if not version.sign_hash:
        return True
    record = version.record if "record" in version.__dict__ else None
    if record is None:
        from app.models.medical_record import MedicalRecord
        record = await db.get(MedicalRecord, version.medical_record_id)
    snapshot = record.patient_snapshot if record else None
    submitted_iso = record.submitted_at.isoformat() if record and record.submitted_at else ""
    recomputed = compute_sign_hash(
        content_text=content_text_of(version.content),
        patient_snapshot=snapshot,
        doctor_id=version.triggered_by or "",
        submitted_at_iso=submitted_iso,
        prev_hash=version.prev_hash or GENESIS_HASH,
    )
    return recomputed == version.sign_hash
