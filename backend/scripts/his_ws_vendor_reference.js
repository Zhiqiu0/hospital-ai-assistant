/**
 * MediScribe × HIS 对接 · 厂商侧 WebSocket 参考实现（Node.js 版，配套《接口规范》v1.2 第 7 章）
 *
 * 与 Python 版（his_ws_vendor_reference.py）功能完全一致，演示贵方要做的全部 4 件事：
 *   ① 签名握手建立 wss 长连接（断线自动重连）
 *   ② 发送 encounter_admit 接诊推送，接收我方 ack
 *   ③ 接收 record_writeback（病历回写→写库）与 record_refresh（通知界面刷新），回 ack
 *   ④ 心跳：收到 ping 回 pong
 *
 * 部署形态（已双方确认）：本逻辑写进全科客户端，每台诊室电脑各自建一条连接，
 * 全院共用同一套 appId/appSecret；病历回写由我方云端自动发回接诊的那台诊室。
 *
 * 运行（Node.js 16+）：
 *   npm install ws
 *   node his_ws_vendor_reference.js --app-id xxx --secret xxx
 */
const crypto = require("crypto");
const WebSocket = require("ws");

const WS_URL = "wss://mediscribe.cn/api/v1/his/ws";

/* ══════════ 签名（规范 2.2：两处共用同一个函数）══════════
 * sign = Hex( HMAC_SHA256( appSecret, app_id + timestamp + nonce + tail ) )
 * tail 是两处唯一的区别：握手时 = 固定字符串 "handshake"；发消息时 = payload 的 JSON 原文 */
function makeSign(appId, timestamp, nonce, tail, secret) {
  return crypto.createHmac("sha256", secret)
    .update(appId + timestamp + nonce + tail, "utf8").digest("hex");
}

/* 组装一条带签名的消息。⚠ 核心三步，顺序不能乱：
 * 1. payload 只序列化一次，存进变量；2. 用这个字符串拼串算签名；
 * 3. 把同一个字符串原样拼进消息体——不要让 JSON 库再转第二次，
 *    否则字段顺序/空格一变签名就对不上（联调最常见的坑）。 */
function signedMessage(type, payload, appId, secret) {
  const payloadStr = JSON.stringify(payload);              // 第 1 步：只转这一次
  const timestamp = String(Date.now());                    // 13 位毫秒，每次现取
  const nonce = crypto.randomUUID().replace(/-/g, "");     // 每条消息现生成，绝不复用
  const sign = makeSign(appId, timestamp, nonce, payloadStr, secret); // 第 2 步
  const msgId = "his-" + crypto.randomUUID().slice(0, 12);
  return `{"type": "${type}", "msg_id": "${msgId}", "app_id": "${appId}", ` +
         `"timestamp": "${timestamp}", "nonce": "${nonce}", "sign": "${sign}", ` +
         `"payload": ${payloadStr}}`;                      // 第 3 步：原样拼进去
}

/* 业务示例数据（接诊推送，字段见规范 3.1）*/
function admitSample() {
  return {
    visit_id: "20260811000101",          // 就诊流水号：整个来回的关联主键
    hospital_code: "H33052300001",       // 医疗机构代码（示例值，联调时换贵方实际代码）
    patient_name: "测试患者", gender: "female", birth_date: "1968-05-20",
    dept_code: "1230024", dept_name: "全科", // 本次接诊科室：科室表「本地ID」+名称
    // doctor_code=医生工号：我方按它把患者派到对应医生的工作台。
    // 工号未在我方注册时 ack 返回 code=40007（message 带具体工号），
    // 属正常业务提示——把该医生工号加入我方账号名单后重推即可。
    doctor_code: "001", doctor_name: "张医生",
    visit_type: "outpatient", is_first_visit: true,
    vitals: { height: "158", weight: "62", bp_systolic: "162", bp_diastolic: "96" },
  };
}

/* ══════════ 主逻辑：④件事都在这里 ══════════ */
function connect(appId, secret, retryDelay = 1000) {
  // ① 握手：四个参数拼在 URL 上，tail 用固定词 "handshake"
  const ts = String(Date.now());
  const nonce = crypto.randomUUID().replace(/-/g, "");
  const sign = makeSign(appId, ts, nonce, "handshake", secret);
  const ws = new WebSocket(
    `${WS_URL}?app_id=${appId}&timestamp=${ts}&nonce=${nonce}&sign=${sign}`);

  ws.on("open", () => {
    console.log("[✓] 握手成功，长连接已建立");
    retryDelay = 1000; // 连上即重置退避
    // ② 演示发一条接诊推送（实际接入：医生在 HIS 点"接诊"时触发）
    ws.send(signedMessage("encounter_admit", admitSample(), appId, secret));
    console.log("[→] 已发送接诊推送");
  });

  ws.on("message", (raw) => {
    const msg = JSON.parse(raw.toString());
    if (msg.type === "ack") {            // 我方对贵方消息的确认：code=0 即成功
      const p = msg.payload || {};
      console.log(`[←] 收到 ack：code=${p.code} message=${p.message} (应答 ${p.ack_msg_id})`);
    } else if (msg.type === "ping") {    // ④ 心跳：回 pong 即可
      ws.send(signedMessage("pong", {}, appId, secret));
    } else if (msg.type === "record_writeback") {
      // ③ 病历回写：payload = 完整病历字段 + visit_id（字段见规范 3.2）
      // 贵方在这里【写数据库】：按 visit_id 定位就诊，病历存为"草稿/待确认"状态，
      // 重复收到同一 visit_id 为覆盖更新（幂等，见规范 2.5）。写完回 ack。
      console.log(`[←] 收到病历回写 visit_id=${msg.payload.visit_id}，此处写库…`);
      ws.send(signedMessage("ack", {
        code: 0, message: "success", trace_id: crypto.randomUUID(),
        data: { record_id: "贵方落库后的病历ID" }, ack_msg_id: msg.msg_id,
      }, appId, secret));
    } else if (msg.type === "record_refresh") {
      // ③ 刷新通知：让诊室 HIS 界面把该就诊的病历页重新从库里加载显示
      console.log(`[←] 收到刷新通知 visit_id=${msg.payload.visit_id}，此处通知界面刷新…`);
      ws.send(signedMessage("ack", {
        code: 0, message: "success", trace_id: crypto.randomUUID(),
        data: {}, ack_msg_id: msg.msg_id,
      }, appId, secret));
    }
  });

  // 断线自动重连：1s、2s、4s…指数退避，最大 60s（规范 7.4）
  ws.on("close", () => {
    console.log(`[!] 连接断开，${retryDelay / 1000}s 后重连`);
    setTimeout(() => connect(appId, secret, Math.min(retryDelay * 2, 60000)), retryDelay);
  });
  ws.on("error", (err) => console.log(`[!] 连接错误：${err.message}`)); // close 会跟着触发
}

/* 入口：node his_ws_vendor_reference.js --app-id xxx --secret xxx */
const args = process.argv.slice(2);
const appId = args[args.indexOf("--app-id") + 1];
const secret = args[args.indexOf("--secret") + 1];
if (!appId || !secret) {
  console.log("用法：node his_ws_vendor_reference.js --app-id <我方分配的appId> --secret <我方分配的appSecret>");
  process.exit(1);
}
connect(appId, secret);
