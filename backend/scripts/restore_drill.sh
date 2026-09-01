#!/usr/bin/env bash
# 备份恢复演练（2026-09-02 新增）
#
# 为什么需要：备份脚本每天 03:00 在跑、日志也一直是 OK，但**从来没有人验证过
# 那些 .sql.gz 到底能不能恢复出一个可用的库**。没验证过恢复的备份不算备份——
# 等级保护测评与医院评审都会问这一条，而真要用到备份的那天没有第二次机会。
#
# 做法：把指定（默认最新）的一份备份恢复进一次性库 restore_drill，逐项核对，
# 核对完立刻销毁。全程不碰生产库：库名硬编码，且恢复前显式断言它不是生产库名。
#
# 用法：
#   ./restore_drill.sh                      # 演练最新一份备份
#   ./restore_drill.sh 20260901_030001      # 演练指定日期的备份
#
# 任一步失败即非零退出，可直接挂 cron 做月度演练。
set -euo pipefail

BACKUP_ROOT="/var/backups/mediscribe"
DRILL_DB="restore_drill"
COMPOSE_DIR="/app"

# ── 选备份 ──────────────────────────────────────────────────────────────────
STAMP="${1:-}"
if [ -z "$STAMP" ]; then
  STAMP="$(ls -1 "${BACKUP_ROOT}" | sort | tail -1)"
fi
DUMP="${BACKUP_ROOT}/${STAMP}/postgres_medassist.sql.gz"
[ -f "$DUMP" ] || { echo "找不到备份文件：$DUMP"; exit 1; }
echo "=== 恢复演练：${STAMP}（$(du -h "$DUMP" | cut -f1)）==="

DB_CONTAINER="$(cd "$COMPOSE_DIR" && docker compose ps -q db)"
[ -n "$DB_CONTAINER" ] || { echo "db 容器未运行"; exit 1; }

# 生产库名从容器环境读，用来断言演练库绝不与之同名
PROD_DB="$(docker exec "$DB_CONTAINER" sh -c 'echo $POSTGRES_DB')"
[ "$DRILL_DB" != "$PROD_DB" ] || { echo "演练库名与生产库同名，拒绝执行"; exit 1; }

psql_drill() { docker exec -i "$DB_CONTAINER" sh -c "psql -U \$POSTGRES_USER -d ${DRILL_DB} -v ON_ERROR_STOP=1 $*"; }
psql_admin() { docker exec -i "$DB_CONTAINER" sh -c "psql -U \$POSTGRES_USER -d postgres -v ON_ERROR_STOP=1 $*"; }

cleanup() {
  docker exec "$DB_CONTAINER" rm -f /tmp/restore_drill.sql.gz 2>/dev/null || true
  psql_admin -q -c "\"DROP DATABASE IF EXISTS ${DRILL_DB};\"" >/dev/null 2>&1 || true
}
trap cleanup EXIT   # 中途失败也要销毁演练库，不留垃圾占磁盘

# ── 恢复 ────────────────────────────────────────────────────────────────────
echo "[1/3] 建一次性库并恢复..."
psql_admin -q -c "\"DROP DATABASE IF EXISTS ${DRILL_DB};\"" -c "\"CREATE DATABASE ${DRILL_DB};\"" >/dev/null
docker cp "$DUMP" "${DB_CONTAINER}:/tmp/restore_drill.sql.gz"
docker exec "$DB_CONTAINER" sh -c "gunzip -c /tmp/restore_drill.sql.gz | psql -U \$POSTGRES_USER -d ${DRILL_DB} -v ON_ERROR_STOP=1 -q" >/dev/null
echo "    恢复完成，无错误"

# ── 核对 ────────────────────────────────────────────────────────────────────
# 只查"恢复出来的库能不能真的用"，不比对行数——备份是昨天的，与今天不同属正常
echo "[2/3] 核对..."
check() {  # check 描述 SQL 最小值
  local label="$1" sql="$2" min="$3" got
  got="$(psql_drill -t -A -c "\"${sql}\"" | tr -d '[:space:]')"
  if [ "${got:-0}" -ge "$min" ]; then
    printf '    OK  %-22s %s\n' "$label" "$got"
  else
    printf '    FAIL %-22s %s（应 ≥ %s）\n' "$label" "$got" "$min"; exit 1
  fi
}
check "业务表"       "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 20
check "索引"         "SELECT count(*) FROM pg_indexes WHERE schemaname='public'" 50
check "外键约束"     "SELECT count(*) FROM information_schema.table_constraints WHERE constraint_schema='public' AND constraint_type='FOREIGN KEY'" 20
check "医保诊断字典" "SELECT count(*) FROM diagnosis_codes" 40000
check "质控规则"     "SELECT count(*) FROM qc_rules" 1
check "患者档案"     "SELECT count(*) FROM patients" 1
check "病历"         "SELECT count(*) FROM medical_records" 1
# 档案纵向数据存 JSONB，恢复后必须仍能按结构取值（不能退化成字符串）
check "JSONB 档案可查" \
  "SELECT count(*) FROM patients WHERE profile IS NOT NULL AND profile <> '{}'::jsonb" 1
# alembic 版本在，说明恢复出来的库能继续跑迁移，而不是一个死库
VER="$(psql_drill -t -A -c '"SELECT version_num FROM alembic_version;"' | tr -d '[:space:]')"
[ -n "$VER" ] || { echo "    FAIL alembic_version 为空，该库无法继续迁移"; exit 1; }
printf '    OK  %-22s %s\n' "alembic 版本" "$VER"

echo "[3/3] 销毁演练库..."
echo "=== 演练通过：${STAMP} 可恢复 ==="
