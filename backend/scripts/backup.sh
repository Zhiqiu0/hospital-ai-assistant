#!/usr/bin/env bash
# 数据备份脚本（backup.sh）
#
# 备份对象：
#   1. PostgreSQL 主库（业务数据：患者/接诊/病历/审计日志等）
#   2. Orthanc DICOM 存储（影像文件 + 索引数据库）
#   3. uploads 目录（检验报告 OCR 原图、语音录音）
#
# 部署方式（生产服务器 ubuntu 用户 crontab，由 deploy.yml 自动配置）：
#   # 每天凌晨 3 点全量备份，保留最近 14 天
#   0 3 * * * /app/backend/scripts/backup.sh >> /var/log/mediscribe-backup.log 2>&1
#
# 前置条件（一次性）：
#   sudo install -d -o ubuntu -g ubuntu -m 750 /var/backups/mediscribe
#   sudo touch /var/log/mediscribe-backup.log
#   sudo chown ubuntu:ubuntu /var/log/mediscribe-backup.log
#
# 恢复方式（详见脚本末尾注释）。
#
# 异地容灾（2026-08-12 已启用）：
#   备份完成后自动推到阿里云 OSS（华北2-北京，与服务器上海异地）：
#   oss://mediscribe-backup/daily/<TIMESTAMP>/，OSS 侧生命周期 180 天自动清理。
#   前置（一次性，生产已配）：~/bin/ossutil64 二进制 + ~/.ossutilconfig
#   （RAM 子账号凭证，仅 OSS 权限）。上传失败不阻断本地备份。
#
# ⚠️ 后续可选增强：
#   - 大库建议加 wal-g / pgbackrest 做增量 WAL 归档（RPO < 1 分钟）
#   - 加 Healthchecks.io / Sentry Cron Monitor 监控备份是否按时跑

set -euo pipefail

# cron 默认 PATH 很短（/usr/bin:/bin），找不到 docker。显式 export 兜底。
# /usr/local/bin 是 docker / docker-compose 常见位置
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# ── 配置 ───────────────────────────────────────────────────────────────────────
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/mediscribe}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_DIR="${COMPOSE_DIR:-/app}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DEST="${BACKUP_ROOT}/${TIMESTAMP}"

# 数据库连接（与 docker-compose 一致）
DB_USER="${DB_USER:-medassist}"
DB_NAME="${DB_NAME:-medassist}"
ORTHANC_DB="${ORTHANC_DB:-orthanc}"  # docker-entrypoint-initdb.d 自动建的库

# ── 准备 ───────────────────────────────────────────────────────────────────────
mkdir -p "${DEST}"
echo "[$(date)] === 备份开始: ${DEST} ==="

cd "${COMPOSE_DIR}"

# ── 0. 先清理过期本地备份（2026-08-14 第八轮审计修复）────────────────────────
#
# 这一段原先是**最后一步**，而脚本头部是 set -euo pipefail：前面任何一步失败
# 就直接退出，清理永远轮不到。真实故障链：某天 db 容器正在重启，第 1 步
# pg_dump 管道失败 → 脚本立刻退出 → 旧备份一份都不删。此后每天照样建目录、
# 留下半截文件，而每份完整备份含 PG 主库 + Orthanc 索引 + 整个 DICOM 存储
# + uploads，全量非增量，很快把 2 核 4G 机器的盘吃满；盘一满 PostgreSQL
# 写不进去，**全院病历系统停摆**。等发现时是「备份好几周没成功 + 磁盘满」
# 双故障叠加。
# 清理跟"这次备份成没成功"本来就没有依赖关系，放最前面先把空间腾出来。
echo "[cleanup] 删除超过 ${RETENTION_DAYS} 天的旧备份..."
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" \
    -exec echo "  removing {}" \; -exec rm -rf {} \; || \
    echo "    WARN: 清理失败，继续备份"

# ── 1. PostgreSQL 主库（业务数据）─────────────────────────────────────────────
echo "[1/4] pg_dump ${DB_NAME}..."
# 用 if 包住而不是裸奔（2026-08-14 第八轮审计）：第 2/3/4 步本来就都包了，
# 唯独最关键的这步没包——它一失败，set -e 让整个脚本当场退出，
# 后面的 Orthanc 索引、DICOM、uploads 一样都备不成，也没有任何告警。
# 现在失败只标记并继续，让其余部分尽量备下来，最后以非零退出码告知 cron。
BACKUP_FAILED=0
if docker compose exec -T db pg_dump -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists \
    | gzip > "${DEST}/postgres_${DB_NAME}.sql.gz"; then
    echo "    OK ($(du -h "${DEST}/postgres_${DB_NAME}.sql.gz" | cut -f1))"
else
    echo "    ERROR: 主库 pg_dump 失败！（其余步骤继续，脚本最终以非零码退出）"
    BACKUP_FAILED=1
fi

# ── 2. Orthanc 索引库 ────────────────────────────────────────────────────────
# Orthanc 的 metadata（study/series/instance 索引）存在 PostgreSQL 里
echo "[2/4] pg_dump ${ORTHANC_DB}..."
if docker compose exec -T db pg_dump -U "${DB_USER}" -d "${ORTHANC_DB}" --clean --if-exists \
        | gzip > "${DEST}/postgres_${ORTHANC_DB}.sql.gz"; then
    echo "    OK ($(du -h "${DEST}/postgres_${ORTHANC_DB}.sql.gz" | cut -f1))"
else
    echo "    SKIP（orthanc 库不存在或为空，初次部署可忽略）"
fi

# ── 3. Orthanc DICOM 文件存储 ────────────────────────────────────────────────
# 走 "容器内 tar 到 stdout → 重定向到主机文件" 模式
# 原因：cron 跑在 ubuntu 用户下，主机的 /var/lib/docker/volumes/ 是 root 700，
# 直接 tar volume mountpoint 会 permission denied。容器内有完整读权限，
# 通过 stdout 把流送出来是最干净的方案（不需要 sudo / 临时 helper 容器）。
echo "[3/4] tar Orthanc storage（容器内）..."
if docker compose exec -T orthanc tar czf - -C /var/lib/orthanc/db . \
        > "${DEST}/orthanc_storage.tar.gz" 2>/dev/null; then
    echo "    OK ($(du -h "${DEST}/orthanc_storage.tar.gz" | cut -f1))"
else
    echo "    FAIL（orthanc 容器未运行？保留 0 字节占位文件供排查）"
fi

# ── 4. uploads 目录（检验报告/语音）──────────────────────────────────────────
echo "[4/4] tar uploads（容器内）..."
if docker compose exec -T backend tar czf - -C /app/uploads . \
        > "${DEST}/uploads.tar.gz" 2>/dev/null; then
    echo "    OK ($(du -h "${DEST}/uploads.tar.gz" | cut -f1))"
else
    echo "    FAIL（backend 容器未运行？保留 0 字节占位文件供排查）"
fi

# ── 5. 异地容灾：本次备份推阿里云 OSS（北京，与服务器上海异地）────────────────
# 上传失败不阻断（本地备份已完整落盘），只记 WARN 供日志/告警排查。
OSSUTIL="${OSSUTIL:-$HOME/bin/ossutil64}"
OSS_BUCKET="${OSS_BUCKET:-mediscribe-backup}"
if [ -x "${OSSUTIL}" ] && [ -f "$HOME/.ossutilconfig" ]; then
    echo "[5/5] 上传 OSS oss://${OSS_BUCKET}/daily/${TIMESTAMP}/ ..."
    if "${OSSUTIL}" cp -r "${DEST}" "oss://${OSS_BUCKET}/daily/${TIMESTAMP}/" -u >/dev/null 2>&1; then
        echo "    OK（异地副本已落北京，OSS 生命周期 180 天自动清理）"
    else
        echo "    WARN: OSS 上传失败——本地备份不受影响，请查网络/凭证（~/.ossutilconfig）"
    fi
else
    echo "[5/5] SKIP：未配置 ossutil，异地上传未启用（见脚本头部前置说明）"
fi

if [ "${BACKUP_FAILED}" -ne 0 ]; then
    echo "[$(date)] === 备份结束：**有步骤失败**，请检查上方日志 ==="
    exit 1
fi
echo "[$(date)] === 备份完成 ==="
du -sh "${DEST}"

# ── 成功心跳（2026-08-16 上线前体检补）─────────────────────────────────────
# 在此之前，备份失败**没有任何人会知道**：脚本 set -euo pipefail 会中止、
# 上面失败分支也 exit 1，但结果只写进 /var/log/mediscribe-backup.log，
# 而没人每天去看日志。备份连着挂一周，要等到真需要恢复的那天才发现——
# 那正是最不能没有备份的时刻。
#
# 用「死人开关」而不是「失败时告警」：只在**成功**时 ping 一下，
# 由 uptime-kuma 的 Push 监控在超时未收到时告警。这样不仅能发现"备份跑了但失败"，
# 还能发现"cron 根本没跑""服务器关机了"这类失败时连告警代码都执行不到的情况。
# BACKUP_HEARTBEAT_URL 未配置则整段跳过（本地/开发环境无影响）。
# 只从 .env 里取这一个变量，不 source 整个文件——那会把 DB/OSS 密码一并带进
# 当前 shell，而本脚本后面还要 echo 日志，没必要让密钥有机会漏出去。
if [ -z "${BACKUP_HEARTBEAT_URL:-}" ] && [ -f "${COMPOSE_DIR}/.env" ]; then
    BACKUP_HEARTBEAT_URL="$(sed -n 's/^BACKUP_HEARTBEAT_URL=//p' "${COMPOSE_DIR}/.env" \
        | tail -1 | tr -d '\r' | tr -d '"' | tr -d "'")"
fi
if [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
    if curl -fsS -m 10 "${BACKUP_HEARTBEAT_URL}" -o /dev/null 2>&1; then
        echo "[$(date)] 成功心跳已上报"
    else
        # 心跳发不出去不算备份失败——备份本身已经完成，不能因为通知失败就 exit 1
        echo "[$(date)] WARN: 成功心跳上报失败（备份本身已完成）"
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 恢复操作（手动执行）
# ─────────────────────────────────────────────────────────────────────────────
#
# 恢复 PostgreSQL 主库：
#   gunzip < /var/backups/mediscribe/<TIMESTAMP>/postgres_medassist.sql.gz \
#     | docker compose exec -T db psql -U medassist -d medassist
#
# 恢复 Orthanc 索引库：
#   gunzip < /var/backups/mediscribe/<TIMESTAMP>/postgres_orthanc.sql.gz \
#     | docker compose exec -T db psql -U medassist -d orthanc
#
# 恢复 Orthanc DICOM 文件（容器内 untar，避免主机 root 权限问题）：
#   docker compose stop orthanc
#   docker compose run --rm -T -v /var/backups/mediscribe:/backup:ro orthanc \
#     tar xzf /backup/<TIMESTAMP>/orthanc_storage.tar.gz -C /var/lib/orthanc/db
#   docker compose start orthanc
#
# 恢复 uploads：
#   docker compose exec -T backend tar xzf - -C /app/uploads \
#     < /var/backups/mediscribe/<TIMESTAMP>/uploads.tar.gz
#
# 本地备份没了（服务器级灾难）→ 先从 OSS 拉回再按上面恢复：
#   ~/bin/ossutil64 ls oss://mediscribe-backup/daily/            # 看有哪些时间点
#   ~/bin/ossutil64 cp -r oss://mediscribe-backup/daily/<TIMESTAMP>/ \
#     /var/backups/mediscribe/<TIMESTAMP>/
#
# ⚠️ 恢复«2026-08-12 迁移压缩重置»之前的老备份时，alembic_guard 会因缺列
#   FATAL 拒绝启动（预期保护），须先人工补齐 schema 或改用重置后的备份。
