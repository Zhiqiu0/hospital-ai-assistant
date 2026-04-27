#!/usr/bin/env bash
# 数据备份脚本（backup.sh）
#
# 备份对象：
#   1. PostgreSQL 主库（业务数据：患者/接诊/病历/审计日志等）
#   2. Orthanc DICOM 存储（影像文件 + 索引数据库）
#   3. uploads 目录（检验报告 OCR 原图、语音录音）
#
# 部署方式（生产服务器 root crontab）：
#   # 每天凌晨 3 点全量备份，保留最近 14 天
#   0 3 * * * /app/backend/scripts/backup.sh >> /var/log/mediscribe-backup.log 2>&1
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
docker compose exec -T db pg_dump -U "${DB_USER}" -d "${ORTHANC_DB}" --clean --if-exists \
    | gzip > "${DEST}/postgres_${ORTHANC_DB}.sql.gz" || {
        echo "    SKIP（orthanc 库不存在或为空，初次部署可忽略）"
    }

# ── 3. Orthanc DICOM 文件存储 ────────────────────────────────────────────────
# orthanc_storage volume 实际位置由 docker volume inspect 查
# 直接 tar volume 挂载点，比走 DICOMweb 导出快几个量级
ORTHANC_VOL=$(docker volume inspect -f '{{ .Mountpoint }}' app_orthanc_storage 2>/dev/null || \
              docker volume inspect -f '{{ .Mountpoint }}' hospital-ai-assistant_orthanc_storage 2>/dev/null || \
              echo "")
if [[ -n "${ORTHANC_VOL}" ]] && [[ -d "${ORTHANC_VOL}" ]]; then
    echo "[3/4] tar Orthanc storage from ${ORTHANC_VOL}..."
    tar czf "${DEST}/orthanc_storage.tar.gz" -C "${ORTHANC_VOL}" . 2>&1 | head -3 || true
    echo "    OK ($(du -h "${DEST}/orthanc_storage.tar.gz" | cut -f1))"
else
    echo "[3/4] SKIP Orthanc storage（volume 未找到，确认 compose 项目名后调整）"
fi

# ── 4. uploads 目录（检验报告/语音）──────────────────────────────────────────
UPLOADS_VOL=$(docker volume inspect -f '{{ .Mountpoint }}' app_uploads_data 2>/dev/null || \
              docker volume inspect -f '{{ .Mountpoint }}' hospital-ai-assistant_uploads_data 2>/dev/null || \
              echo "")
if [[ -n "${UPLOADS_VOL}" ]] && [[ -d "${UPLOADS_VOL}" ]]; then
    echo "[4/4] tar uploads from ${UPLOADS_VOL}..."
    tar czf "${DEST}/uploads.tar.gz" -C "${UPLOADS_VOL}" . 2>&1 | head -3 || true
    echo "    OK ($(du -h "${DEST}/uploads.tar.gz" | cut -f1))"
else
    echo "[4/4] SKIP uploads（volume 未找到）"
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
# 恢复 Orthanc DICOM 文件：
#   docker compose stop orthanc
#   ORTHANC_VOL=$(docker volume inspect -f '{{ .Mountpoint }}' app_orthanc_storage)
#   tar xzf /var/backups/mediscribe/<TIMESTAMP>/orthanc_storage.tar.gz -C "${ORTHANC_VOL}"
#   docker compose start orthanc
#
# 恢复 uploads：
#   UPLOADS_VOL=$(docker volume inspect -f '{{ .Mountpoint }}' app_uploads_data)
#   tar xzf /var/backups/mediscribe/<TIMESTAMP>/uploads.tar.gz -C "${UPLOADS_VOL}"
