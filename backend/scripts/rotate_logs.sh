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
# 用**昨天**的日期命名（2026-08-14 第六轮审计修复）：
# 本脚本在 00:05 执行，此刻切走的是刚过去那一天的日志，而原先用 date +%Y%m%d
# 取当天日期——归档 app-20260814.log.gz 里装的其实是 8月13日 的内容。
# 查 bug 按日期找会打开错误的文件（本项目铁律是先看 error.log，日期错位很误事）。
# date -d yesterday 是 GNU coreutils 语法，生产是 Ubuntu，可用。
STAMP=$(date -d "yesterday" +%Y%m%d 2>/dev/null || date +%Y%m%d)

[ -d "${LOGS_DIR}" ] || { echo "[rotate_logs] 目录不存在: ${LOGS_DIR}"; exit 0; }

for name in app error; do
    src="${LOGS_DIR}/${name}.log"
    # 文件不存在或为空则跳过（服务刚起、当天无 error 都属正常）
    [ -s "${src}" ] || continue
    dest="${LOGS_DIR}/${name}-${STAMP}.log"
    # 同日二次执行必须追加而不是覆盖（2026-08-13 第五轮审计修复）：
    # 原先只判 ${dest}（.log）是否存在，但第一轮结束时它已经被 gzip 成 .log.gz、
    # .log 不复存在——第二轮判定不成立，走 mv 新建再 `gzip -f`，-f 直接覆盖当天
    # 已有归档，前一段日志静默消失。查 bug 全靠这些日志，丢了就没法追溯。
    # gzip 流可以合法拼接（gunzip 会按多个成员依次解开），故直接追加压缩流。
    if [ -e "${dest}.gz" ]; then
        gzip -c "${src}" >> "${dest}.gz" && : > "${src}"
        echo "[rotate_logs] ${name}.log -> 追加到 $(basename "${dest}").gz"
        continue
    fi
    if [ -e "${dest}" ]; then
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
