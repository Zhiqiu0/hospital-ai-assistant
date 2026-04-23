"""
实时语音识别 WebSocket 代理（/api/v1/ai/voice-stream）

架构：
  浏览器 PCM 音频流 → 本服务 WebSocket → 阿里云 DashScope Paraformer-realtime-v2 → 识别结果 → 浏览器

协议：
  - 客户端连接时通过 query 参数传入 JWT（WebSocket 无法设置自定义请求头）
  - 客户端握手后可直接发送二进制 PCM16 帧（16kHz / 16bit / mono）
  - 客户端发送文本消息 "finish" 表示录音结束
  - 服务端回推 JSON 文本消息：
      {"type":"started"}            任务已就绪，可开始发送音频
      {"type":"partial","text":...} 中间结果（尚可变化）
      {"type":"final","text":...}   最终句子（不会再变）
      {"type":"error","message":..} 任何异常
      {"type":"finished"}           任务结束
"""
# ── 标准库 ────────────────────────────────────────────────────────────────────
import asyncio
import json
import logging
import uuid
from typing import Optional

# ── 第三方库 ──────────────────────────────────────────────────────────────────
import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

# ── 本地模块 ──────────────────────────────────────────────────────────────────
from app.config import settings
from app.core.security import verify_token_str

logger = logging.getLogger(__name__)

router = APIRouter()

# 阿里云 DashScope Paraformer 实时 ASR WebSocket 入口
DASHSCOPE_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
# 采用中文通用领域的实时识别模型
ASR_MODEL = "paraformer-realtime-v2"
# 采样率/位宽，须与前端 AudioWorklet 产出的 PCM 严格一致
ASR_SAMPLE_RATE = 16000


@router.websocket("/voice-stream")
async def voice_stream(websocket: WebSocket, token: str = Query(...)):
    """实时语音识别 WebSocket 代理端点。"""
    # 1. 鉴权：WebSocket 不能用 Authorization 头，token 走 query 参数
    try:
        user_id = verify_token_str(token)
    except Exception as exc:
        # FastAPI 要求 accept 之后才能 close；这里用 1008 表示策略违规
        await websocket.close(code=1008, reason=f"auth failed: {exc}")
        return

    # 2. 未配置 API Key 时直接拒绝（前端应走上传兜底）
    if not settings.aliyun_api_key:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "服务未配置阿里云 API Key"})
        await websocket.close()
        return

    await websocket.accept()
    logger.info("voice-stream 接入 user=%s", user_id)

    task_id = uuid.uuid4().hex
    upstream: Optional[websockets.WebSocketClientProtocol] = None

    try:
        # 3. 连接阿里云（鉴权通过 Authorization 头）
        upstream = await websockets.connect(
            DASHSCOPE_WS_URL,
            additional_headers={
                "Authorization": f"bearer {settings.aliyun_api_key}",
                "X-DashScope-DataInspection": "enable",
            },
            max_size=2**24,
            ping_interval=20,
            ping_timeout=20,
        )

        # 4. 发送 run-task 指令，启动识别任务
        run_task_msg = {
            "header": {
                "action": "run-task",
                "task_id": task_id,
                "streaming": "duplex",
            },
            "payload": {
                "task_group": "audio",
                "task": "asr",
                "function": "recognition",
                "model": ASR_MODEL,
                "parameters": {
                    "format": "pcm",
                    "sample_rate": ASR_SAMPLE_RATE,
                    "disfluency_removal_enabled": False,
                    "language_hints": ["zh"],
                },
                "input": {},
            },
        }
        await upstream.send(json.dumps(run_task_msg))

        # 5. 启动双向转发
        client_closed = asyncio.Event()

        async def pump_downlink():
            """阿里云 → 浏览器：解析识别结果并转发。"""
            try:
                async for raw in upstream:
                    if isinstance(raw, bytes):
                        continue  # 下行理论上只有文本
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    header = msg.get("header", {})
                    event = header.get("event")
                    payload = msg.get("payload", {})
                    if event == "task-started":
                        await _safe_send_json(websocket, {"type": "started"})
                    elif event == "result-generated":
                        sentence = payload.get("output", {}).get("sentence", {})
                        text = sentence.get("text", "")
                        # sentence_end=True 表示这句已终稿，否则为中间结果
                        is_final = bool(sentence.get("sentence_end")) or bool(
                            sentence.get("end_time") and sentence.get("words")
                            and sentence["words"][-1].get("fixed")
                        )
                        msg_type = "final" if is_final else "partial"
                        await _safe_send_json(websocket, {"type": msg_type, "text": text})
                    elif event == "task-finished":
                        await _safe_send_json(websocket, {"type": "finished"})
                        client_closed.set()
                        return
                    elif event == "task-failed":
                        err_msg = header.get("error_message") or "阿里云识别任务失败"
                        await _safe_send_json(websocket, {"type": "error", "message": err_msg})
                        client_closed.set()
                        return
            except websockets.ConnectionClosed:
                client_closed.set()
            except Exception as exc:
                logger.warning("pump_downlink 异常: %s", exc)
                await _safe_send_json(websocket, {"type": "error", "message": str(exc)})
                client_closed.set()

        async def pump_uplink():
            """浏览器 → 阿里云：转发 PCM 二进制帧，收到 finish 文本时触发 finish-task。"""
            try:
                while not client_closed.is_set():
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if "bytes" in msg and msg["bytes"] is not None:
                        await upstream.send(msg["bytes"])
                    elif "text" in msg and msg["text"] is not None:
                        if msg["text"] == "finish":
                            await upstream.send(json.dumps({
                                "header": {
                                    "action": "finish-task",
                                    "task_id": task_id,
                                    "streaming": "duplex",
                                },
                                "payload": {"input": {}},
                            }))
                            # 不立即退出，等 task-finished 回推后由 downlink 触发 client_closed
            except WebSocketDisconnect:
                pass
            except Exception as exc:
                logger.warning("pump_uplink 异常: %s", exc)
            finally:
                client_closed.set()

        await asyncio.gather(pump_downlink(), pump_uplink())

    except Exception as exc:
        logger.error("voice-stream 主流程异常: %s", exc, exc_info=True)
        await _safe_send_json(websocket, {"type": "error", "message": str(exc)})
    finally:
        if upstream is not None:
            try:
                await upstream.close()
            except Exception:
                pass
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass
        logger.info("voice-stream 结束 task=%s", task_id)


async def _safe_send_json(ws: WebSocket, data: dict) -> None:
    """向已可能关闭的客户端 WebSocket 安全发送 JSON，忽略异常。"""
    if ws.client_state == WebSocketState.DISCONNECTED:
        return
    try:
        await ws.send_json(data)
    except Exception:
        pass
