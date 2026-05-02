#!/bin/sh
set -e

echo "[entrypoint] 初始化数据库..."
python init_db.py

echo "[entrypoint] 执行增量迁移..."
python migrate.py

echo "[entrypoint] 补充默认配置数据..."
python seed_config.py

echo "[entrypoint] 启动服务..."
# uvicorn 启动参数说明（2026-05-02 治本调优）：
#   --timeout-keep-alive 600 ：跟 nginx keepalive_timeout 600s 对齐，nginx ↔ backend
#                              链路 idle 不被过早关（默认 5s 太短，长会话场景下
#                              connection 频繁重建，加重 ERR_CONNECTION_CLOSED）
#   --workers 2              ：从默认 1 worker 升到 2，让并发请求不被串行排队
#                              （4G 内存实测够，每 worker ≈ 200MB）
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 \
    --timeout-keep-alive 600 \
    --workers 2
