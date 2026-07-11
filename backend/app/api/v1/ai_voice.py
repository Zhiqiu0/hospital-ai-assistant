"""
AI 语音路由聚合（/api/v1/ai/voice-records/*, /api/v1/ai/voice-structure）

Round 5 瘦身：原文件 431 行超标，按职责拆到同目录子模块（各自建 router，本文件聚合）——
  _ai_voice_helpers   : ASR 转写 + meta 前缀剥离（非端点辅助）
  ai_voice_records    : POST /voice-records/upload、GET /voice-records/{id}/audio-token、
                        GET /voice-records/{id}/audio、DELETE /voice-records/{id}
  ai_voice_structure  : POST /voice-structure
本文件只保留主 router 并 include 子路由（路径/方法/依赖零改动，行为完全一致）。

注：本模块的 router 由 ai.py 以 include_router(..., dependencies=[限速]) 挂载，
子路由不带额外 prefix，最终端点路径与限速依赖均与拆分前一致。

端点列表：
  POST   /voice-records/upload              上传语音文件（含 ASR 转写）
  GET    /voice-records/{id}/audio-token    颁发短期音频令牌
  GET    /voice-records/{id}/audio          播放语音文件（query-token 鉴权）
  DELETE /voice-records/{id}               删除语音记录及磁盘文件
  POST   /voice-structure                   语音文本结构化为问诊字段
"""
from fastapi import APIRouter

# 同目录子路由（各自持有 APIRouter，端点路径与拆分前逐字一致）
from app.api.v1 import ai_voice_records, ai_voice_structure

# 主 router：由 ai.py 以 prefix="/ai" + 限速依赖挂载；
# 子路由不带额外 prefix，拼回后端点路径与原文件完全相同。
router = APIRouter()
router.include_router(ai_voice_records.router)
router.include_router(ai_voice_structure.router)
