#!/bin/sh
set -e

# 迁移单通道（2026-08-12 收口）：alembic 是唯一 schema 真源。
# guard 只打标记不执行 DDL（存量库版本缺失/指向旧链时 stamp 到基线），
# upgrade 负责全部建表/改表（全新库从基线一步建成）。
echo "[entrypoint] alembic 迁移守卫..."
python alembic_guard.py

echo "[entrypoint] alembic 迁移..."
alembic upgrade head

echo "[entrypoint] 种子数据（表结构已由 alembic 建好）..."
python init_db.py

echo "[entrypoint] 补充默认配置数据..."
python seed_config.py

echo "[entrypoint] 启动服务..."
# uvicorn 启动参数说明（2026-05-02 治本调优）：
#   --timeout-keep-alive 600 ：跟 nginx keepalive_timeout 600s 对齐，nginx ↔ backend
#                              链路 idle 不被过早关（默认 5s 太短，长会话场景下
#                              connection 频繁重建，加重 ERR_CONNECTION_CLOSED）
#   --workers 2              ：从默认 1 worker 升到 2，让并发请求不被串行排队
#                              （4G 内存实测够，每 worker ≈ 200MB）
#   --ws-ping-interval/timeout ：**实质禁用 WebSocket 协议层心跳**
#                              （2026-09-01 HIS 联调失败模式审计）
#      uvicorn 默认每 20s 发一个 RFC6455 PING 控制帧（opcode 0x9），20s 收不到
#      PONG 就主动断连。这个要求**接口规范里一个字都没写**——规范 7.4 承诺的是
#      应用层 JSON 心跳（我方每 30s 发 type=ping，空闲 90s 判失效）。
#      发给厂商的两份参考实现用的是 Python websockets / Node ws，它们会自动回
#      PONG，于是这个隐式要求被完全掩盖了。而 HIS 厂商客户端多是 Delphi/C#/Java
#      自撸帧解析，只实现文档里的 JSON ping/pong——现场表现就是「握手成功，每
#      40 秒左右被踢一次，没有任何错误码」，是联调当天最难定位的一类问题。
#      我方应用层心跳已完整覆盖死连接检测，协议层这层冗余，故关掉。
#      为什么用大数而不是 0：CLI 参数 type=float 不接受 None，而 websockets 里
#      只有 None 才是禁用，传 0 会让 keepalive_ping 变成 await sleep(0) 忙循环。
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 \
    --timeout-keep-alive 600 \
    --ws-ping-interval 86400 \
    --ws-ping-timeout 86400 \
    --workers 2
