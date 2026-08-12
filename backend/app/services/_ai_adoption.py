"""AI 采纳度量——编辑距离数据管道（services/_ai_adoption.py）

2026-08-12 反馈闭环：路线图"反馈编辑距离"项落地。

问题：看板里的"AI 建议采纳率"只统计医生对质控建议点 useful/useless，
反映不了核心问题——AI 生成的病历草稿医生到底改了多少才敢签发。
改得越少说明草稿质量越高，这是 AI 病历质量最真实的行为信号。

方案：数据其实早就在库里——record_versions 存了每一版 AI 草稿
（source='ai_generate/ai_polish/ai_supplement'）和签发终稿
（source='doctor_signed'）。签发时取最近一版 AI 草稿与终稿算文本相似度
（difflib.SequenceMatcher.ratio，标准库、字符级、对中文友好），
落在签发版本的 ai_similarity / ai_base_version_no 两列，看板按窗口聚合。

边界：
  - 纯手写签发（签发前没有任何 AI 版本）不计，两列为 NULL；
  - 度量列不参与 sign_hash 哈希链（它是运营指标不是病历内容，
    且签发后不应因指标回填破坏链校验）；
  - 计算失败绝不阻断签发（签发是命门主路径，指标是旁路）。
"""
import difflib
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medical_record import RecordVersion
from app.services._record_signature import content_text_of

logger = logging.getLogger(__name__)

# 相似度计算的单侧文本长度上限：SequenceMatcher 最坏 O(n²)，病历正文通常
# 几 KB，此上限只防极端脏数据拖慢签发主路径（超长部分截断后再比）。
_MAX_COMPARE_CHARS = 30_000


def text_similarity(a: str, b: str) -> float:
    """两段文本的相似度（0~1，1=完全相同）。空文本一律记 0。"""
    a = (a or "")[:_MAX_COMPARE_CHARS]
    b = (b or "")[:_MAX_COMPARE_CHARS]
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 4)


async def latest_ai_version(
    db: AsyncSession, medical_record_id: str
) -> Optional[RecordVersion]:
    """取该病历最近一版 AI 生成的版本（ai_generate/ai_polish/ai_supplement）。

    选"最近一版"而非"第一版"：医生通常在最后一次 AI 输出的基础上修改签发，
    与最近一版比才反映"医生改了多少"；与第一版比会混入 AI 自我迭代的差异。
    """
    return (await db.execute(
        select(RecordVersion)
        .where(
            RecordVersion.medical_record_id == medical_record_id,
            RecordVersion.source.like("ai_%"),
        )
        .order_by(RecordVersion.version_no.desc())
        .limit(1)
    )).scalars().first()


async def annotate_sign_similarity(
    db: AsyncSession, version: RecordVersion, final_text: str
) -> None:
    """签发钩子：给签发版本回填 AI 相似度。非致命——任何异常只记日志不阻断签发。

    用 SAVEPOINT（begin_nested）包住指标读写（2026-08-12 复检修复）：指标查询
    若在 DB 层出错，会把整个签发事务标记为 aborted，光靠 except 兜不住——
    后续 commit 照样抛 PendingRollbackError 让签发失败。回滚到 SAVEPOINT
    只丢弃指标操作，签发主事务不受污染。
    """
    try:
        async with db.begin_nested():
            base = await latest_ai_version(db, version.medical_record_id)
            if base is None:
                return  # 纯手写签发，无 AI 草稿可比
            base_text = content_text_of(base.content)
            if not base_text:
                return
            version.ai_similarity = text_similarity(base_text, final_text)
            version.ai_base_version_no = base.version_no
    except Exception as exc:
        # 指标计算失败不能影响签发主路径，记 warning 供事后排查
        logger.warning(
            "ai_adoption.annotate: failed record_id=%s err=%s",
            version.medical_record_id, exc,
        )


async def adoption_stats(db: AsyncSession, window_start: datetime) -> dict:
    """近窗口 AI 采纳度聚合（供质量健康看板）。

    返回：
      total          : 有 AI 草稿参与的签发数
      avg_similarity : 平均相似度（终稿 vs 最近一版 AI 草稿）
      high_adoption  : 相似度 ≥0.8 的签发数（草稿基本原样采纳）
      low_adoption   : 相似度 <0.5 的签发数（医生大改，草稿质量待查）
    """
    sims = (await db.execute(
        select(RecordVersion.ai_similarity).where(
            RecordVersion.source == "doctor_signed",
            RecordVersion.ai_similarity.isnot(None),
            RecordVersion.created_at >= window_start,
        )
    )).scalars().all()
    total = len(sims)
    return {
        "total": total,
        "avg_similarity": round(sum(sims) / total, 3) if total else None,
        "high_adoption": sum(1 for s in sims if s >= 0.8),
        "low_adoption": sum(1 for s in sims if s < 0.5),
    }
