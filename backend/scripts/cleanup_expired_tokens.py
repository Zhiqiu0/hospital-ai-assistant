# -*- coding: utf-8 -*-
"""过期吊销令牌清理脚本（scripts/cleanup_expired_tokens.py，2026-08-28 全量体检）。

背景：revoked_tokens 表"只进不出"——每次登出插一行，token 有效期 30 天，
过期后该行对安全再无意义（is_token_revoked 只对未过期 token 有判定价值），
但此前无任何清理机制，以年为单位缓慢膨胀并被每日备份反复携带。
模型 docstring 里早写了清理 SQL，本脚本把它落成 cron 可执行的形式。

清理口径：expires_at 早于当前时刻的行（token 本身已失效，删除不影响任何
在途会话的吊销判定）。幂等，重复执行安全。

部署方式（生产 ubuntu crontab，由 deploy.yml 自动配置）：
  # 每天 04:10 跑，避开 03:00 备份与 04:00 语音清理
  10 4 * * * cd /app && docker compose exec -T backend \
      python scripts/cleanup_expired_tokens.py >> /var/log/mediscribe-voice-cleanup.log 2>&1

跑法（容器内）：python scripts/cleanup_expired_tokens.py
退出码：0 正常；非 0 有未处理异常（cron 日志可见 traceback）。
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete  # noqa: E402

from app.database import AsyncSessionLocal  # noqa: E402
from app.models.revoked_token import RevokedToken  # noqa: E402


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(RevokedToken).where(RevokedToken.expires_at < datetime.now())
        )
        await db.commit()
        print(f"[cleanup_expired_tokens] {datetime.now():%F %T} 清理 {result.rowcount} 行过期吊销令牌")


if __name__ == "__main__":
    asyncio.run(main())
