# -*- coding: utf-8 -*-
"""MediScribe × HIS 对接 · 厂商侧 WebSocket 参考实现（配套《接口规范》v1.3 第 7 章）

与 v1.3 规范一致，2026-08-15。

本文件演示贵方程序要做的全部 4 件事，可直接运行
（python 3.10+，pip install websockets；3.8/3.9 请装 websockets<14）：
  ① 签名握手建立 wss 长连接（断线自动重连）
  ② 发送 encounter_admit 接诊推送，接收我方 ack
  ③ 接收 record_writeback（病历回写→写库）与 record_refresh（通知界面刷新），回 ack
  ④ 心跳：收到 ping 回 pong

换成贵方实际语言开发时，本文件可当伪代码逐行对照。

部署形态（已双方确认）：本逻辑写进全科客户端，**每台诊室电脑的客户端启动时
各自建一条连接**，全院共用同一套 appId/appSecret，无需按机器做任何配置或登记；
病历回写会由我方云端自动发回接诊的那台诊室，贵方不用做任何区分处理。

运行示例（凭证换成我方分配的正式 appId/appSecret）：
  python his_ws_vendor_reference.py --app-id xxx --secret xxx
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import time
import uuid

import websockets  # 唯一第三方依赖

WS_URL = "wss://mediscribe.cn/api/v1/his/ws"


# ══════════════ 签名（规范 2.2：两处共用同一个函数）══════════════
def make_sign(app_id: str, timestamp: str, nonce: str, tail: str, secret: str) -> str:
    """sign = Hex( HMAC_SHA256( appSecret, app_id + timestamp + nonce + tail ) )

    tail 的取值是两处唯一的区别：
      握手时  tail = 固定字符串 "handshake"
      发消息时 tail = payload 的 JSON 原文（见 signed_message 的三步）
    """
    text = f"{app_id}{timestamp}{nonce}{tail}"
    return hmac.new(secret.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_message(msg_type: str, payload: dict, app_id: str, secret: str) -> str:
    """组装一条带签名的消息。⚠ 核心三步，顺序不能乱：

    第 1 步：payload 只序列化一次，存成字符串变量；
    第 2 步：用这个字符串拼串算签名；
    第 3 步：把同一个字符串原样拼进消息体——不要让 JSON 库再转第二次，
             否则字段顺序/空格一变，签名就对不上了（联调最常见的坑）。
    """
    payload_str = json.dumps(payload, ensure_ascii=False)          # 第 1 步
    timestamp = str(int(time.time() * 1000))                       # 13 位毫秒，每次现取
    nonce = uuid.uuid4().hex                                       # 每条消息现生成，绝不复用
    sign = make_sign(app_id, timestamp, nonce, payload_str, secret)  # 第 2 步
    msg_id = f"his-{uuid.uuid4().hex[:12]}"                        # 消息唯一号，重发时不变
    return ('{"type": "%s", "msg_id": "%s", "app_id": "%s", "timestamp": "%s", '
            '"nonce": "%s", "sign": "%s", "payload": %s}'
            % (msg_type, msg_id, app_id, timestamp, nonce, sign, payload_str))  # 第 3 步


# ══════════════ 业务示例数据（接诊推送，字段见规范 3.1）══════════════
def admit_sample() -> dict:
    return {
        "visit_id": "20260514001401",          # 就诊流水号：整个来回的关联主键
        # hospital_code 是幂等键的另一半（规范 2.5：hospital_code + visit_id），
        # 同一次就诊的推送与回写必须与 visit_id 一起保持完全一致
        "hospital_code": "H33052300001",       # 医疗机构代码（示例值，联调时换贵方实际代码）
        # patient_no：贵方 HIS 里对同一个人稳定不变的编号（病案号 / 患者主索引号 /
        # 居民健康档案号均可）。选填但强烈建议——我方按
        # 「身份证 → patient_no → 手机号+姓名」的顺序跨就诊认人，三者全缺时
        # 同一位患者每次就诊都会新建档案，医生看不到其既往病历与过敏史（规范 3.1）
        "patient_no": "BA20260514001",
        "patient_name": "测试患者", "gender": "female", "birth_date": "1968-05-20",
        "id_card": "330523196805200022", "phone": "13800138000",
        # 过敏史/既往史属患者纵向档案，跟随患者而非本次就诊；有则一并推
        "allergy_history": "青霉素过敏", "past_history": "高血压 10 年",
        "dept_code": "1230024", "dept_name": "全科",  # 本次接诊科室的编码+名称（示例取自贵方科室表）
        # doctor_code=医生工号：我方按它把患者派到对应医生的工作台。
        # 工号未在我方注册时 ack 返回 code=40007（message 带具体工号），
        # 属正常业务提示——把该医生工号加入我方账号名单后重推即可。
        "doctor_code": "001", "doctor_name": "张医生",
        "visit_type": "outpatient", "is_first_visit": True,
        # 体征选填：接诊界面已录的实测值有则一并推（字段见 3.1 表 vitals.*）
        "vitals": {"height": "158", "weight": "62",
                   "bp_systolic": "162", "bp_diastolic": "96"},
    }


# ══════════════ 主循环：④件事都在这里 ══════════════
async def run_once(app_id: str, secret: str) -> None:
    # ① 握手：四个参数拼在 URL 上，tail 用固定词 "handshake"
    # ⚠ 握手 nonce 是一次性的：下面这四行每次（重）连都必须重新执行，
    #   不要把算好的 url 存成配置或成员变量后原样复用——那会被判为重放，
    #   固定返回 HTTP 403，且与 appId 错、签名错的表现完全一样（规范 7.2）。
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = make_sign(app_id, ts, nonce, "handshake", secret)
    url = f"{WS_URL}?app_id={app_id}&timestamp={ts}&nonce={nonce}&sign={sign}"

    async with websockets.connect(url) as ws:
        print("[✓] 握手成功，长连接已建立")

        # ② 演示发一条接诊推送（实际接入：医生在 HIS 点"接诊"时触发）
        await ws.send(signed_message("encounter_admit", admit_sample(), app_id, secret))
        print("[→] 已发送接诊推送")

        async for raw in ws:  # 常驻收消息
            msg = json.loads(raw)
            mtype = msg.get("type")

            if mtype == "ack":  # 我方对贵方消息的确认：code=0 即成功
                p = msg.get("payload", {})
                print(f"[←] 收到 ack：code={p.get('code')} message={p.get('message')} "
                      f"(应答消息 {p.get('ack_msg_id')})")

            elif mtype == "ping":  # ④ 心跳：回 pong 即可
                await ws.send(signed_message("pong", {}, app_id, secret))

            elif mtype == "record_writeback":
                # ③ 病历回写：payload = 完整病历字段 + visit_id（字段见规范 3.2）
                # 贵方在这里【写数据库】，病历存为"草稿/待确认"。
                #
                # ⚠️ 无条件写库：本机是否接诊过该患者一律不要判断。
                #    回写通常路由回接诊那台诊室，但来源诊室掉线时我方会改投
                #    任意一条在线连接（写的是全院共享库，与诊室无关）。
                #    按「是不是本机接诊的」过滤会导致该份病历彻底丢失（规范 7.2）。
                #
                # ⚠️ 幂等键是三段：visit_id + record_type + record_no（见规范 2.5）
                #    · 该键对应的文书尚无 → 新建；已有 → 覆盖更新
                #    · 住院一次就诊有多份文书（入院记录 / 多次日常病程 / 出院记录…），
                #      必须靠 record_no 区分。若只按 visit_id 定位，
                #      15 份日常病程会互相覆盖，最终只剩最后一天那份。
                #    · 我方本期恒下发 record_no（门诊/急诊恒为 "1"），
                #      请一律按三段键定位，不要为门诊做两段键的特例分支。
                #
                # ⚠️ 补投：连接断开后由我方对账任务重新发起的重投会使用新的
                #    msg_id，只按 msg_id 判重会产生重复病历，务必以上面的
                #    业务幂等键为准（规范 7.4）。
                payload = msg["payload"]
                visit_id = payload.get("visit_id")
                record_type = payload.get("record_type")
                record_no = payload.get("record_no")  # 住院多份文书的序号
                print(f"[←] 收到病历回写 visit_id={visit_id} "
                      f"type={record_type} no={record_no}，此处按三段键写库…")
                await ws.send(signed_message("ack", {
                    "code": 0, "message": "success", "trace_id": uuid.uuid4().hex,
                    "data": {"record_id": "贵方落库后的病历ID"},
                    "ack_msg_id": msg["msg_id"],   # 指向被应答的那条消息
                }, app_id, secret))

            elif mtype == "record_refresh":
                # ③ 刷新通知：让诊室 HIS 界面把该就诊的病历页重新从库里加载显示。
                # target 与本次写入的 record_type 完全一致（原样透传，不做任何
                # 加/减后缀的加工），据此定位要刷新的是哪一类文书（规范 3.3）。
                visit_id = msg["payload"].get("visit_id")
                target = msg["payload"].get("target")
                print(f"[←] 收到刷新通知 visit_id={visit_id} target={target}，"
                      f"此处刷新该类文书的界面…")
                await ws.send(signed_message("ack", {
                    "code": 0, "message": "success", "trace_id": uuid.uuid4().hex,
                    "data": {}, "ack_msg_id": msg["msg_id"],
                }, app_id, secret))


async def main(app_id: str, secret: str) -> None:
    """断线自动重连：1s、2s、4s…指数退避，最大 60s（规范 7.4）。

    注意「正常关闭」也要退避：我方服务端的两条主要关闭路径（90 秒空闲超时、
    ack 重发耗尽）都是正常关闭（close code 1000），此时 `async for` 是无异常
    正常结束的。若只在异常分支退避，就会变成「连上→被关→立刻重连」的
    零延迟紧循环。所以下面把两种结束方式并到同一条退避路径上。
    """
    delay = 1
    while True:
        started = time.time()
        try:
            await run_once(app_id, secret)
            print(f"[!] 连接已被对端正常关闭，{delay}s 后重连")
        except Exception as exc:
            print(f"[!] 连接断开：{exc}，{delay}s 后重连")
        # 退避复位的条件是「这次连接活够久」，而不是「连上过」：
        # 若连上就复位，遇到「握手成功但立刻被关」的故障会退化成 1s 紧循环。
        if time.time() - started >= 60:
            delay = 1
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MediScribe HIS 对接厂商侧参考实现")
    parser.add_argument("--app-id", required=True, help="我方分配的 appId")
    parser.add_argument("--secret", required=True, help="我方分配的 appSecret")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.app_id, args.secret))
    except KeyboardInterrupt:
        print("\n[退出]")
