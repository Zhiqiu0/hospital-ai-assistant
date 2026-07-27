"""模拟 HIS 客户端（联调彩排用）：扮演厂商侧，验证我方 WS 服务端全流程。

行为完全按接口规范 v1.1 第 7 章：
  1. 签名握手建连（query 带 app_id/timestamp/nonce/sign）
  2. 发一条 encounter_admit 接诊推送，等我方 ack
  3. 常驻：回应我方 ping（回 pong）；收到 record_writeback / record_refresh
     时打印 payload 并回 ack（模拟 HIS 写库+刷新成功）

用法（后端需已启动且 HIS_ADAPTER_ENABLED=true）：
  venv\\Scripts\\python.exe scripts\\his_ws_mock_client.py \\
      --url ws://127.0.0.1:8010/api/v1/his/ws --app-id appHIS --secret secret-key
"""
import argparse
import asyncio
import json
import time
import uuid

import websockets

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 引 app 包
from app.his_adapter.signing import compute_sign  # noqa: E402

ADMIT_SAMPLE = {
    "visit_id": "20260727000101", "hospital_code": "H32050701121",
    "patient_name": "彩排患者", "gender": "female", "birth_date": "1968-05-20",
    "dept_code": "0101", "dept_name": "全科", "doctor_code": "001",
    "doctor_name": "张医生", "visit_type": "outpatient", "is_first_visit": True,
    "vitals": {"height": "158", "weight": "62",
               "bp_systolic": "162", "bp_diastolic": "96"},
}


def signed_message(msg_type: str, payload: dict, app_id: str, secret: str,
                   msg_id: str = None) -> str:
    """按规范 7.3 组装消息：payload 只序列化一次，签的和发的是同一个字符串。"""
    payload_str = json.dumps(payload, ensure_ascii=False)   # ① 只转这一次
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(app_id, ts, nonce, payload_str, secret)  # ② 签它
    msg_id = msg_id or f"his-{uuid.uuid4().hex[:12]}"
    return ('{"type": "%s", "msg_id": "%s", "app_id": "%s", "timestamp": "%s", '
            '"nonce": "%s", "sign": "%s", "payload": %s}'
            % (msg_type, msg_id, app_id, ts, nonce, sign, payload_str))  # ③ 原样发它


async def run(url: str, app_id: str, secret: str) -> None:
    # 握手：query 参数签名，待签串末段为固定词 "handshake"
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(app_id, ts, nonce, "handshake", secret)
    full = f"{url}?app_id={app_id}&timestamp={ts}&nonce={nonce}&sign={sign}"
    print(f"[连接] {full[:80]}...")
    async with websockets.connect(full) as ws:
        print("[✓] 握手成功，连接已建立")
        await ws.send(signed_message("encounter_admit", ADMIT_SAMPLE, app_id, secret))
        print(f"[→] 已发送接诊推送 visit_id={ADMIT_SAMPLE['visit_id']}")

        async for raw in ws:
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "ack":
                p = msg.get("payload", {})
                print(f"[←] ack: code={p.get('code')} message={p.get('message')} "
                      f"data={p.get('data')} (应答 {p.get('ack_msg_id')})")
            elif mtype == "ping":  # 我方服务端心跳 → 回 pong
                await ws.send(signed_message("pong", {}, app_id, secret))
            elif mtype == "pong":
                pass
            elif mtype in ("record_writeback", "record_refresh"):
                # 模拟 HIS：打印回写内容并回成功 ack（带 record_id 模拟落库结果）
                print(f"[←] 收到 {mtype}:")
                print(json.dumps(msg.get("payload", {}), ensure_ascii=False, indent=2))
                ack_payload = {"code": 0, "message": "success",
                               "trace_id": uuid.uuid4().hex,
                               "data": {"record_id": "MOCK-DOC-001"},
                               "ack_msg_id": msg["msg_id"]}
                await ws.send(signed_message("ack", ack_payload, app_id, secret))
                print(f"[→] 已回 ack（应答 {msg['msg_id']}）")
            else:
                print(f"[?] 未知消息类型 {mtype}: {raw[:120]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="模拟 HIS WebSocket 客户端")
    parser.add_argument("--url", default="ws://127.0.0.1:8010/api/v1/his/ws")
    parser.add_argument("--app-id", default="appHIS")
    parser.add_argument("--secret", default="secret-key")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.url, args.app_id, args.secret))
    except KeyboardInterrupt:
        print("\n[退出] 手动断开")
