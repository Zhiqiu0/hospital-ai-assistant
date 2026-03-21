#!/bin/sh
set -e

echo "[entrypoint] 初始化数据库..."
python init_db.py

echo "[entrypoint] 执行增量迁移..."
python migrate.py

echo "[entrypoint] 补充默认配置数据..."
python seed_config.py

echo "[entrypoint] 启动服务..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8010
