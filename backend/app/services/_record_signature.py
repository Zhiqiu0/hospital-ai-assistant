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


async def verify_chain(db: AsyncSession) -> list[dict]:
    """校验全局签名链的链接完整性，返回问题清单（空列表 = 链完好）。

    为什么必须有这个函数（2026-08-13 第五轮审计修复）：
      verify_version 只做**单行自校验**——它把该行自己存的 prev_hash 当作哈希
      输入之一去重算，从不去查这个 prev_hash 是否真的对应链上某一环。
      于是"链"退化成了"每行一个无密钥自校验和"，链接关系形同虚设：
        · 删掉链中任一签发版本 → 后继版本的 prev_hash 指向一个已不存在的哈希，
          没有任何代码会发现（而本模块头部注释明确宣称这能被检出）
        · 改正文后按同一 prev_hash 重算 sign_hash（算法就在仓库里、无密钥）
          → 单行自校验通过，同样零痕迹
      补上链接校验后，这两类篡改都会暴露。

    校验方式为"引用存在性"而非"严格线性"：latest_chain_hash 取的是**全局链尾**
    （所有病历共用一条链），且它的文档说明并发签发会产生合法分叉。严格按
    created_at 逐环比对会把分叉误报成断裂，所以改为——每一环的 prev_hash 必须
    是 GENESIS，或者确实等于链上某一环的 sign_hash。分叉时两环引用同一个前驱，
    判定通过；而删除/重算会让引用悬空，判定失败。

    已知边界：链尾版本被改后重算哈希，因为没有后继引用它，链接校验查不出来
    （任何哈希链都需要外部锚点才能防尾部篡改）。单行自校验同样查不出重算。
    这是当前方案的固有上限，要根治得引入 CA/UKey 数字签名或外部时间戳。

    返回的每项形如 {"medical_record_id": str, "version_no": int, "issue": "..."}。
    """
    rows = (await db.execute(
        select(RecordVersion)
        .where(RecordVersion.sign_hash.isnot(None))
        .order_by(RecordVersion.created_at)
    )).scalars().all()

    known_hashes = {v.sign_hash for v in rows}
    issues: list[dict] = []
    for v in rows:
        prev = v.prev_hash or GENESIS_HASH
        # ① 链接校验：prev_hash 必须指向链上真实存在的一环
        if prev != GENESIS_HASH and prev not in known_hashes:
            issues.append({
                "medical_record_id": v.medical_record_id,
                "version_no": v.version_no,
                "issue": "链断裂：prev_hash 指向的上一环不存在"
                         "（中间版本被删除，或其哈希被重算）",
            })
        # ② 单行自校验：正文/快照/医生/签发时间有没有被回改
        if not await verify_version(db, v):
            issues.append({
                "medical_record_id": v.medical_record_id,
                "version_no": v.version_no,
                "issue": "内容被篡改：正文或患者快照与签发时的哈希对不上",
            })
    return issues
