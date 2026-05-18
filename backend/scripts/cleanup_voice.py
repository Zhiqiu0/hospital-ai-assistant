"""语音录音文件定时清理脚本（scripts/cleanup_voice.py）

清理策略：
  扫描所有 audio_file_path 非空、created_at 早于 cutoff 的 VoiceRecord：
    1. 删除磁盘上的原始音频文件（uploads/voice_records/<encounter_id>/<uuid>.webm）
    2. 把 audio_file_path 和 mime_type 字段置 None
    3. raw_transcript / structured_inquiry / draft_record / transcript_summary
       这些医生整理后的成果一律保留——它们是病历的关键证据，不能动

  清理后：
    - has_audio = False（VoiceRecord.audio_file_path 为空）
    - admin 页"有录音"列显示"无"
    - 工作台音频播放控件不再渲染

部署方式（生产服务器 ubuntu 用户 crontab，由 deploy.yml 自动配置）：
  # 每天凌晨 4 点跑，避开 3 点的备份高峰
  0 4 * * * docker compose -f /app/docker-compose.yml exec -T backend \
      python scripts/cleanup_voice.py >> /var/log/mediscribe-voice-cleanup.log 2>&1

  说明：默认保留 30 天；如需调整设环境变量 VOICE_RETENTION_DAYS（容器内）。

跑法（容器内）：
  python scripts/cleanup_voice.py            # 删 30 天前的（实际执行）
  python scripts/cleanup_voice.py --dry-run  # 只列出会删什么，不实际删
  python scripts/cleanup_voice.py --days 7   # 临时改成 7 天

退出码：
  0 正常结束（无论是否有删除项）
  非 0 表示有未处理的异常，cron 日志可见 traceback
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 让脚本能直接 import app.*（与 smoke_pacs_orthanc.py 同一套路）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models.voice_record import VoiceRecord  # noqa: E402

# 默认保留天数：与 admin 侧需求一致，环境变量可覆盖
DEFAULT_RETENTION_DAYS = int(os.environ.get("VOICE_RETENTION_DAYS", "30"))

# uploads 目录：容器内 /app/uploads；本地 backend/uploads
# 与 ai_voice.py 的 uploads_root 算法保持一致（脚本 → 上一级 backend → uploads）
UPLOADS_ROOT = Path(__file__).resolve().parents[1] / "uploads"

logger = logging.getLogger("cleanup_voice")


def _setup_logging() -> None:
    """与项目其他脚本保持一致：module.action: message + 时间戳"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def cleanup(days: int, dry_run: bool) -> int:
    """执行一轮清理，返回删除/置空的记录数。

    Args:
        days: 保留天数，超过此天数且仍带音频文件的记录会被处理
        dry_run: True 时只打印不实际删除（用于人工核验）

    Returns:
        本次处理的记录数（dry-run 下也返回匹配数）
    """
    # cutoff 用 naive UTC：TimestampMixin.created_at 是 TIMESTAMP WITHOUT TIME ZONE
    # （由数据库 func.now() 填充，容器时区为 UTC），所以本端传 naive datetime 才能比较
    cutoff = datetime.utcnow() - timedelta(days=days)
    logger.info("cleanup.start: cutoff=%s dry_run=%s", cutoff.isoformat(), dry_run)

    processed = 0
    file_missing = 0
    async with AsyncSessionLocal() as db:
        # 选出"有音频文件 + 时间早于 cutoff"的记录
        result = await db.execute(
            select(VoiceRecord)
            .where(VoiceRecord.audio_file_path.is_not(None))
            .where(VoiceRecord.created_at < cutoff)
            .order_by(VoiceRecord.created_at)
        )
        records = result.scalars().all()
        logger.info("cleanup.scan: matched=%d records", len(records))

        for r in records:
            rel = r.audio_file_path or ""
            abs_path = UPLOADS_ROOT / rel
            # 先尝试删物理文件；文件已不存在视为已清理过，仅更新 DB 字段
            if abs_path.exists():
                if dry_run:
                    logger.info("cleanup.would_delete: id=%s path=%s size=%dB",
                                r.id, rel, abs_path.stat().st_size)
                else:
                    try:
                        abs_path.unlink()
                        logger.info("cleanup.deleted: id=%s path=%s", r.id, rel)
                    except OSError as exc:
                        # 删文件失败不阻断整批清理，记录后继续
                        logger.warning("cleanup.delete_failed: id=%s path=%s err=%s",
                                       r.id, rel, exc)
                        continue
            else:
                file_missing += 1
                logger.info("cleanup.file_missing: id=%s path=%s (DB only cleanup)",
                            r.id, rel)

            if not dry_run:
                # 只清音频相关字段，保留所有转写/结构化结果
                await db.execute(
                    update(VoiceRecord)
                    .where(VoiceRecord.id == r.id)
                    .values(audio_file_path=None, mime_type=None)
                )
            processed += 1

        if not dry_run:
            await db.commit()

    logger.info("cleanup.done: processed=%d file_missing=%d dry_run=%s",
                processed, file_missing, dry_run)
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="清理过期语音录音文件（保留转写文本）")
    parser.add_argument("--days", type=int, default=DEFAULT_RETENTION_DAYS,
                        help=f"保留天数，默认 {DEFAULT_RETENTION_DAYS}（可被 VOICE_RETENTION_DAYS 环境变量覆盖）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出会被删除的记录，不实际删除")
    args = parser.parse_args()

    _setup_logging()
    asyncio.run(cleanup(days=args.days, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
