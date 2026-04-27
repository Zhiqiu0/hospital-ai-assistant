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
# ⚠️ 这是基础版本。生产建议：
#   - 备份完成后用 rclone / aws s3 sync 推到对象存储（异地容灾）
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

# ── 1. PostgreSQL 主库（业务数据）─────────────────────────────────────────────
echo "[1/4] pg_dump ${DB_NAME}..."
docker compose exec -T db pg_dump -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists \
    | gzip > "${DEST}/postgres_${DB_NAME}.sql.gz"
echo "    OK ($(du -h "${DEST}/postgres_${DB_NAME}.sql.gz" | cut -f1))"

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

# ── 5. 清理过期备份（保留最近 N 天）──────────────────────────────────────────
echo "[cleanup] 删除超过 ${RETENTION_DAYS} 天的旧备份..."
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" \
    -exec echo "  removing {}" \; -exec rm -rf {} \;

echo "[$(date)] === 备份完成 ==="
du -sh "${DEST}"

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
