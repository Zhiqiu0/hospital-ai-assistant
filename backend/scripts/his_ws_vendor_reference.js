/**
 * MediScribe × HIS 对接 · 厂商侧 WebSocket 参考实现（Node.js 版，配套《接口规范》v1.3 第 7 章）
 *
 * 与 v1.3 规范一致，2026-08-15。
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
 *    否则字段顺序/空格一变签名就对不上（联调最常见的坑）。
 *
 * ⚠ 我方是按**贵方实际发出的那串字节**验签的，不会重新序列化 payload。
 *   所以「算签名用的字符串」与「消息里 payload 的字符串」必须是同一个：
 *   中文转不转义（\uXXXX）、键的顺序、有没有缩进空格，只要两处有一点不同，
 *   签名一律对不上（我方回 code=40001），而公式本身并没有错。
 *
 * msgId（规范 7.4）：每条**新**消息一个新号；只有「同一条消息因超时重发」
 * 时才把上次的号原样传进来，我方据此判重、不重复处理。 */
function signedMessage(type, payload, appId, secret, msgIdIn) {
  const payloadStr = JSON.stringify(payload);              // 第 1 步：只转这一次
  const timestamp = String(Date.now());                    // 13 位毫秒，每次现取
  const nonce = crypto.randomUUID().replace(/-/g, "");     // 每条消息现生成，绝不复用
  const sign = makeSign(appId, timestamp, nonce, payloadStr, secret); // 第 2 步
  // 先去掉连字符再截，与 Python 版逐字对齐（直接 slice 会截出
  // "his-6b6c1e1e-cf2" 这种中间夹连字符、只有 11 位有效随机位的值）
  const msgId = msgIdIn || "his-" + crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  return `{"type": "${type}", "msg_id": "${msgId}", "app_id": "${appId}", ` +
         `"timestamp": "${timestamp}", "nonce": "${nonce}", "sign": "${sign}", ` +
         `"payload": ${payloadStr}}`;                      // 第 3 步：原样拼进去
}

/* 业务示例数据（接诊推送，字段见规范 3.1）*/
function admitSample() {
  return {
    visit_id: "20260514001401",          // 就诊流水号：整个来回的关联主键
    // hospital_code 是幂等键的另一半（规范 2.5：hospital_code + visit_id），
    // 同一次就诊的推送与回写必须与 visit_id 一起保持完全一致
    hospital_code: "H33052300001",       // 医疗机构代码（示例值，联调时换贵方实际代码）
    // patient_no：贵方 HIS 里对同一个人稳定不变的编号（病案号 / 患者主索引号 /
    // 居民健康档案号均可）。选填但强烈建议——我方按
    // 「身份证 → patient_no → 手机号+姓名」的顺序跨就诊认人，三者全缺时
    // 同一位患者每次就诊都会新建档案，医生看不到其既往病历与过敏史（规范 3.1）
    patient_no: "BA20260514001",
    patient_name: "测试患者", gender: "female", birth_date: "1968-05-20",
    id_card: "330523196805200022", phone: "13800138000",
    // 过敏史/既往史属患者纵向档案，跟随患者而非本次就诊；有则一并推
    allergy_history: "青霉素过敏", past_history: "高血压 10 年",
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
  // ⚠ 握手 nonce 是一次性的：下面这三行每次（重）连都必须重新执行，
  //   不要把算好的 URL 存成配置或成员变量后原样复用——那会被判为重放，
  //   固定返回 HTTP 403，且与 appId 错、签名错的表现完全一样（规范 7.2）。
  const ts = String(Date.now());
  const nonce = crypto.randomUUID().replace(/-/g, "");
  const sign = makeSign(appId, ts, nonce, "handshake", secret);
  const ws = new WebSocket(
    `${WS_URL}?app_id=${appId}&timestamp=${ts}&nonce=${nonce}&sign=${sign}`);

  // 空闲看门狗（规范 7.4：任一方连续 90 秒未收到任何消息即判定连接失效）。
  // Node 的 ws 客户端不会主动发 ping、也不自带空闲检测，遇到半开连接
  // （TCP 没断、对端已死）会永久挂着不重连——那台诊室从此收不到任何回写，
  // 而客户端界面上一切正常。我方每 30 秒下发一次 ping，所以 90 秒收不到
  // 任何消息就说明连接已经废了，主动断开走重连。
  let idleTimer = null;
  const resetIdle = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      console.log("[!] 90 秒未收到任何消息，判定连接失效，主动断开重连");
      ws.terminate();               // 触发 close → 走下面的退避重连
    }, 90000);
  };

  // 退避复位的条件是「这次连接活够久」，不是「连上过」（与 Python 版一致）：
  // 若一 open 就把退避清回 1 秒，遇到「握手成功但立刻被关」的故障
  // （例如我方 ack 重发耗尽主动断开）就会退化成 1 秒一次的紧循环，
  // 既连不上又一直打我方服务。这里记下连上的时刻，close 时再判断。
  let openedAt = 0;

  ws.on("open", () => {
    console.log("[✓] 握手成功，长连接已建立");
    openedAt = Date.now();
    resetIdle();
    // ② 演示发一条接诊推送（实际接入：医生在 HIS 点"接诊"时触发）
    ws.send(signedMessage("encounter_admit", admitSample(), appId, secret));
    console.log("[→] 已发送接诊推送");
  });

  // 整个回调包 try/catch：JSON.parse 失败、或 payload 缺字段导致读属性抛错时，
  // 未捕获异常会让 Node 进程直接退出，close 事件走不到、重连逻辑失效。
  // 单条消息处理失败不该拖垮长连接。
  ws.on("message", (raw) => {
   try {
    resetIdle();                      // 收到任何消息都刷新空闲计时
    const msg = JSON.parse(raw.toString());
    if (msg.type === "ack") {            // 我方对贵方消息的确认：code=0 即成功
      const p = msg.payload || {};
      console.log(`[←] 收到 ack：code=${p.code} message=${p.message} (应答 ${p.ack_msg_id})`);
    } else if (msg.type === "ping") {    // ④ 心跳：回 pong 即可
      ws.send(signedMessage("pong", {}, appId, secret));
    } else if (msg.type === "record_writeback") {
      // ③ 病历回写：payload = 完整病历字段 + visit_id（字段见规范 3.2）
      // 贵方在这里【写数据库】，病历存为"草稿/待确认"状态，写完回 ack。
      //
      // ⚠️ 无条件写库：本机是否接诊过该患者一律不要判断。
      //    回写通常路由回接诊那台诊室，但来源诊室掉线时我方会改投任意一条
      //    在线连接（写的是全院共享库，与诊室无关）。按「是不是本机接诊的」
      //    过滤会导致该份病历彻底丢失（规范 7.2）。
      //
      // ⚠️ 幂等键是三段：visit_id + record_type + record_no（见规范 2.5）
      //    · 该键对应的文书尚无 → 新建；已有 → 覆盖更新
      //    · 住院一次就诊有多份文书（入院记录 / 多次日常病程 / 出院记录…），
      //      必须靠 record_no 区分。若只按 visit_id 定位，
      //      15 份日常病程会互相覆盖，最终只剩最后一天那份。
      //    · 我方本期恒下发 record_no（门诊/急诊恒为 "1"），
      //      请一律按三段键定位，不要为门诊做两段键的特例分支。
      //
      // ⚠️ 补投：连接断开后由我方对账任务重新发起的重投会使用新的 msg_id，
      //    只按 msg_id 判重会产生重复病历，务必以上面的业务幂等键为准（规范 7.4）。
      const { visit_id, record_type, record_no } = msg.payload;
      console.log(
        `[←] 收到病历回写 visit_id=${visit_id} type=${record_type} no=${record_no}，此处按三段键写库…`
      );
      ws.send(signedMessage("ack", {
        code: 0, message: "success", trace_id: crypto.randomUUID(),
        data: { record_id: "贵方落库后的病历ID" }, ack_msg_id: msg.msg_id,
      }, appId, secret));
    } else if (msg.type === "record_refresh") {
      // ③ 刷新通知：让诊室 HIS 界面把该就诊的病历页重新从库里加载显示。
      // target 与本次写入的 record_type 完全一致（原样透传，不做任何加/减
      // 后缀的加工），据此定位要刷新的是哪一类文书（规范 3.3）。
      console.log(`[←] 收到刷新通知 visit_id=${msg.payload.visit_id} ` +
                  `target=${msg.payload.target}，此处刷新该类文书的界面…`);
      ws.send(signedMessage("ack", {
        code: 0, message: "success", trace_id: crypto.randomUUID(),
        data: {}, ack_msg_id: msg.msg_id,
      }, appId, secret));
    }
   } catch (err) {
    console.log(`[!] 处理消息出错（已忽略该条，连接保持）：${err.message}`);
   }
  });

  // 断线自动重连：1s、2s、4s…指数退避，最大 60s（规范 7.4）
  ws.on("close", () => {
    if (idleTimer) clearTimeout(idleTimer);
    // 活够 60 秒才算「连接是好的」，退避从头开始；否则继续翻倍（见上方 openedAt）
    const delay = openedAt && Date.now() - openedAt >= 60000 ? 1000 : retryDelay;
    console.log(`[!] 连接断开，${delay / 1000}s 后重连`);
    setTimeout(() => connect(appId, secret, Math.min(delay * 2, 60000)), delay);
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
