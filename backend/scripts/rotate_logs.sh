#!/usr/bin/env bash
# 应用日志轮转（rotate_logs.sh）
#
# 2026-08-13 第二轮审计修复的配套：应用侧改用 WatchedFileHandler（多进程安全，
# 检测到文件被换掉就重开），轮转交给本脚本**单进程**执行，杜绝两个 uvicorn
# worker 各自 rename 造成的竞态丢日志。
#
# 部署方式（生产 ubuntu 用户 crontab，由 deploy.yml 自动配置）：
#   5 0 * * * /app/backend/scripts/rotate_logs.sh >> /var/log/mediscribe-backup.log 2>&1
#   （挑 00:05 而不是整点：错开 03:00 备份与整点定时任务高峰）
#
# 行为：把 app.log / error.log 改名为 <name>-YYYYMMDD.log 并 gzip，
# 保留最近 RETENTION_DAYS 天；应用进程下次写入时自动创建新文件。

set -euo pipefail

LOGS_DIR="${LOGS_DIR:-/app/logs}"
RETENTION_DAYS="${LOG_RETENTION_DAYS:-30}"
STAMP=$(date +%Y%m%d)

[ -d "${LOGS_DIR}" ] || { echo "[rotate_logs] 目录不存在: ${LOGS_DIR}"; exit 0; }

for name in app error; do
    src="${LOGS_DIR}/${name}.log"
    # 文件不存在或为空则跳过（服务刚起、当天无 error 都属正常）
    [ -s "${src}" ] || continue
    dest="${LOGS_DIR}/${name}-${STAMP}.log"
    if [ -e "${dest}" ]; then
        # 同一天重复执行：追加而不是覆盖，避免丢掉先前那段
        cat "${src}" >> "${dest}" && : > "${src}"
    else
        mv "${src}" "${dest}"
        # WatchedFileHandler 会在下一条日志时重新创建 app.log/error.log
    fi
    gzip -f "${dest}" 2>/dev/null || true
    echo "[rotate_logs] ${name}.log -> $(basename "${dest}").gz"
done

# 清理过期归档（只删本脚本产出的 <name>-YYYYMMDD.log.gz，不碰别的文件）
find "${LOGS_DIR}" -maxdepth 1 -name "app-*.log.gz" -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true
find "${LOGS_DIR}" -maxdepth 1 -name "error-*.log.gz" -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true

echo "[rotate_logs] 完成（保留 ${RETENTION_DAYS} 天）"
