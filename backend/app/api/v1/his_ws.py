"""HIS WebSocket 通道路由（接口规范 v1.3 第 7 章，方案 B）：/api/v1/his/ws

职责：握手验签 → 接入连接管理器 → 消息循环（分发 ping/ack/接诊推送）→ 心跳与空闲超时。
上行消息我方强制验签；下行（回写/刷新）由 writeback_sender 经 ws_manager 发出。
不挂 require_his_enabled 依赖（那是 HTTP 语义的 503），保险丝在握手处手动检查。
"""
import asyncio
import hashlib
import json
import logging
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.config import settings
from app.his_adapter import ws_protocol as wp
from app.his_adapter.models import AdmitPushRequest
from app.his_adapter.ws_manager import his_ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/his", tags=["HIS对接"])


def _real_client(websocket: WebSocket) -> str:
    """取真实来源 IP（用于排障，也用于 IP 白名单判定）。

    websocket.client 拿到的是 nginx 容器的内网地址（172.19.x.x），全院所有
    连接看起来都来自同一个 IP——联调时「老师连不上」和「有人在扫端口」
    分不出来。

    **为什么取 X-Real-IP 而不是 X-Forwarded-For 首段**（2026-08-15 修正）：
    nginx 这个 location 用的是 `X-Forwarded-For $proxy_add_x_forwarded_for`，
    它把**客户端自己带来的 XFF 原样保留在前面**、再把真实地址追加到末尾。
    也就是说 XFF 首段是攻击者可以随便写的——原实现取首段，日志里的来源 IP
    可被伪造，若再拿它做白名单判定，白名单等于形同虚设（发个
    `X-Forwarded-For: 医院出口IP` 就进来了）。
    而 X-Real-IP 是 nginx 用 proxy_set_header 无条件**覆盖**写入的
    （值为 $remote_addr），客户端伪造不了。XFF 只在没有 X-Real-IP 时兜底，
    且取**末段**（nginx 自己追加的那一段）而不是首段。
    """
    real = websocket.headers.get("x-real-ip", "").strip()
    if real:
        return real
    xff = websocket.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()  # 末段 = 最近一跳代理看到的地址
    c = websocket.client
    return f"{c.host}:{c.port}" if c else "unknown"


def _ip_allowed(client_ip: str) -> bool:
    """来源 IP 是否在白名单内；白名单留空即不限制（默认行为，见 config）。"""
    import ipaddress

    nets = settings.his_ws_allowed_networks()
    if not nets:
        return True
    try:
        addr = ipaddress.ip_address(client_ip.split(":")[0])
    except ValueError:
        return False  # 解析不出来源地址：白名单开着就按拒绝处理
    return any(addr in net for net in nets)


@router.websocket("/ws")
async def his_ws_endpoint(websocket: WebSocket) -> None:
    """HIS 长连接入口：握手验签不过直接拒绝，验签通过后进入消息循环。

    **消息串行处理是有意的**（2026-08-14 第六轮审计评估后保留）：
    审计报"慢 admit 会阻塞 ack 读取"，属实，但改成并发会破坏两件更重要的事——
    msg_id 去重与消息顺序保证，而这两样是联调稳定性的基础（重复接诊、
    ack 错位都会让厂商侧对不上账）。
    容量上也不需要：实测生产 40 条并发语音、45 条 SSE 都无压力，
    而接诊推送一个医院一天不过几百次，串行完全够用。
    真出现阻塞再针对性改（比如只把 admit 处理丢后台、ack 仍走主循环）。
    """
    # 保险丝：HIS 对接开关关闭时拒绝握手（accept 之前 close = 拒绝升级）
    if not settings.his_adapter_enabled:
        await websocket.close(code=4403)
        return
    q = websocket.query_params
    # 分级日志的判据（下面 IP 白名单与验签两处共用）：完全没带凭证 = 健康探测
    # 或端口扫描，不是故障，降到 DEBUG；带了凭证才算真实鉴权失败。
    probe = not q.get("app_id") and not q.get("sign")
    # IP 白名单（默认留空=不限制）：放在验签之前，来源不对就不必再算签名。
    # 单独一条日志与验签失败区分开——否则现场只看到「连不上」，
    # 分不清是密钥不对还是这台机器根本不在名单里。
    client_ip = _real_client(websocket)
    if not _ip_allowed(client_ip):
        (logger.debug if probe else logger.warning)(
            "his_ws.ip_rejected: 来源 IP 不在白名单内 client=%s", client_ip)
        await websocket.close(code=4403)
        return
    err = wp.verify_handshake(
        q.get("app_id", ""), q.get("timestamp", ""), q.get("nonce", ""),
        q.get("sign", ""), settings.his_inbound_app_id,
        settings.his_inbound_app_secret, settings.his_sign_clock_skew_seconds,
    )
    if err is not None:
        # 分级（probe 见上）：完全没带凭证 = 健康探测或端口扫描，不是故障，
        # 降到 DEBUG；带了凭证但不对 = 真实鉴权失败，保持 WARNING。
        # 否则 uptime-kuma 每 60 秒探一次就往 error.log 写一条，一天 1440 条，
        # 把「error.log 只装 WARNING 以上」这个排障入口彻底淹掉。
        log = logger.debug if probe else logger.warning
        log("his_ws.handshake_rejected: %s client=%s", err, client_ip)
        await websocket.close(code=4401)
        return

    # 握手防重放（2026-08-11 审计延期项）：验签通过后一次性 claim 握手 nonce，
    # 拦截时间窗内重放同一握手 URL 建连（截收病历回写）。TTL=时钟偏差窗口+60s 缓冲，
    # 超窗后 timestamp_fresh 已会拒。Redis 不可用时 claim_nonce fail-open，退化为仅
    # 靠时间戳窗口兜底（与上行消息 nonce 同哲学）。
    from app.services.redis_cache import redis_cache
    if not await redis_cache.claim_nonce(
        "his_ws_handshake", q.get("nonce", ""),
        ttl=settings.his_sign_clock_skew_seconds + 60,
    ):
        logger.warning("his_ws.handshake_replay: nonce 重复，拒绝建连 client=%s",
                       client_ip)
        await websocket.close(code=4401)
        return

    await websocket.accept()
    his_ws_manager.register(websocket)  # 每台诊室客户端各一条连接，多条并存
    logger.info("his_ws.connected: client=%s", client_ip)
    ping_task = asyncio.create_task(_ping_loop(websocket))
    try:
        while True:
            # 空闲超时（规范 7.4）：90s 未收到任何消息判定连接失效
            raw = await asyncio.wait_for(
                _receive_text_or_binary(websocket), timeout=wp.IDLE_TIMEOUT
            )
            await _handle_message(websocket, raw)
    except asyncio.TimeoutError:
        logger.warning("his_ws.idle_timeout: 90s 无消息，关闭连接")
        try:
            await websocket.close()
        except Exception:
            pass
    except WebSocketDisconnect:
        # 与 connected 用同一个口径：否则连上记的是真实诊室 IP、断开记的是
        # nginx 容器地址（全院都一样），联调时配不成对，看不出是哪台在反复掉线
        logger.info("his_ws.disconnected: client=%s", client_ip)
    except Exception as exc:  # 连接层意外错误：记日志后走统一清理
        logger.warning("his_ws.connection_error: %s", exc)
    finally:
        ping_task.cancel()
        his_ws_manager.unregister(websocket)


async def _receive_text_or_binary(websocket: WebSocket) -> str:
    """读一条消息并归一成文本（文本帧与二进制帧都收）。

    为什么不直接用 receive_text()（2026-08-15 第十轮审计修复）：
    它遇到二进制帧会抛 KeyError('text')，被消息循环外层当成连接层错误
    → **整条连接被关掉**。厂商侧看到的是「握手成功，但一发消息连接就断」，
    没有 ack、没有错误码、可自动重连于是无限循环；我方 error.log 里也只有
    一句 `his_ws.connection_error: 'text'`，两边都无从下手。
    而 C# 的 ClientWebSocket.SendAsync 必须显式指定 Text/Binary，
    Java、Delphi 的封装同样容易选成二进制——这是厂商很可能踩的第一个坑。
    同一串 UTF-8 JSON 用哪种帧承载语义完全一样，收下即可，不必为此断连。
    """
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    text = message.get("text")
    if text is not None:
        return text
    payload = message.get("bytes") or b""
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        # 既不是文本帧也不是 UTF-8 字节：丢弃该帧但保住连接（返回空串走信封校验失败分支）
        logger.warning("his_ws.non_utf8_frame: 收到非 UTF-8 编码的帧 %d 字节，已丢弃",
                       len(payload))
        return ""


async def _ping_loop(websocket: WebSocket) -> None:
    """心跳任务（规范 7.4）：每 30s 发一次 ping；发送失败即退出（连接已死）。"""
    aid, secret = settings.his_inbound_app_id, settings.his_inbound_app_secret
    try:
        while True:
            await asyncio.sleep(wp.HEARTBEAT_INTERVAL)
            await websocket.send_text(
                wp.build_signed_message(wp.MSG_PING, {}, aid, secret)
            )
    except (asyncio.CancelledError, Exception):
        return


async def _handle_message(websocket: WebSocket, raw: str) -> None:
    """单条上行消息分发：ping/pong 免验签，ack 与业务消息强制验签。"""
    aid, secret = settings.his_inbound_app_id, settings.his_inbound_app_secret
    try:
        env = wp.WsEnvelope.model_validate_json(raw)
    except ValidationError as exc:
        await _reject_bad_envelope(websocket, raw, exc, aid, secret)
        return

    if env.type == wp.MSG_PING:  # 厂商侧心跳 → 立即回 pong
        await websocket.send_text(
            wp.build_signed_message(wp.MSG_PONG, {}, aid, secret)
        )
        return
    if env.type == wp.MSG_PONG:  # 我方 ping 的回应，收到即已刷新空闲计时
        return

    payload_raw = wp.extract_payload_raw(raw, env.payload)
    code = wp.verify_message(
        env, payload_raw, aid, secret, settings.his_sign_clock_skew_seconds
    )

    if env.type == wp.MSG_ACK:
        # 厂商对我方下行消息的应答：验签通过才转给 manager，不通过丢弃（不回 ack 的 ack）
        if code is None:
            matched = his_ws_manager.resolve_ack(
                str(env.payload.get("ack_msg_id", "")), env.payload
            )
            if not matched:
                logger.warning("his_ws.orphan_ack: ack_msg_id=%s 无等待方",
                               env.payload.get("ack_msg_id"))
        else:
            logger.warning("his_ws.ack_verify_failed: code=%s 丢弃", code)
        return

    if code is not None:  # 业务消息验签失败 → 按 2.4 错误码回 ack
        await websocket.send_text(
            wp.build_ack(env.msg_id, code, wp.ERROR_TEXT[code], aid, secret)
        )
        return

    # 业务消息必须带 msg_id（判重与 ack 对应都要用），缺了明确告知而不是静默丢弃。
    # 这条检查放在路由层而不是信封模型上，见 WsEnvelope.msg_id 的说明。
    if not env.msg_id:
        logger.warning("his_ws.missing_msg_id: 业务消息缺 msg_id type=%s", env.type)
        await websocket.send_text(
            wp.build_ack("", 40004, "消息信封不合法：缺少 msg_id", aid, secret)
        )
        return

    if env.type == wp.MSG_ADMIT:
        await _handle_admit(websocket, env, aid, secret)
    else:
        await websocket.send_text(
            wp.build_ack(env.msg_id, 40004, "未知消息类型", aid, secret)
        )


async def _reject_bad_envelope(
    websocket: WebSocket, raw: str, exc: ValidationError, aid: str, secret: str
) -> None:
    """信封字段不合法：尽量回一条 40004 ack，别让厂商对着沉默排查。

    2026-08-15 第十轮审计修复。原先一律静默丢弃，而信封必填项里有个
    **msg_id**——厂商回 ack 时若漏了它（ack 自己的 msg_id 与 ack_msg_id 是两回事，
    很容易只写后者），整条 ack 在这里就没了：我方等不到应答 → 10s×3 重发 →
    判连接失效断开 → 换线重来，而厂商日志里明明写着「我回过 ack」。
    第九轮审计已证实同形态的「ack 漏签名」是最难定位的一类故障。
    回一条带原因的 40004 至少让对方在自己日志里看得见问题出在哪。

    只回业务消息：对端的 ack/pong 不合法时保持沉默，避免两侧互相刷错误消息。
    日志只记字段名不记字段值——payload 里是患者信息，不进日志文件。
    """
    fields = ",".join(".".join(str(x) for x in e["loc"]) for e in exc.errors()[:5])
    salvaged_type, salvaged_id = "", ""
    try:
        probe = json.loads(raw)
        if isinstance(probe, dict):
            salvaged_type = str(probe.get("type") or "")
            salvaged_id = str(probe.get("msg_id") or "")
    except (ValueError, TypeError):
        pass  # 连 JSON 都不是，下面按「未知类型」处理（不回消息）
    logger.warning(
        "his_ws.bad_envelope: 信封不合法 type=%s 缺失/非法字段=%s",
        salvaged_type or "(未知)", fields or "(非 JSON 文本)",
    )
    if salvaged_type in ("", wp.MSG_ACK, wp.MSG_PONG):
        return
    await websocket.send_text(wp.build_ack(
        salvaged_id, 40004, f"消息信封不合法：{fields}", aid, secret))


async def _handle_admit(
    websocket: WebSocket, env: wp.WsEnvelope, aid: str, secret: str
) -> None:
    """接诊推送处理：msg_id 幂等去重 + 载荷校验 + 业务落地 + ack。

    业务落地（2026-08-11 联动冲刺）由 admit_service.handle_admit 完成：
    患者自动建档 + 按工号派医生 + visit_id 幂等建接诊 + 发工作台叫号事件。
    """
    from app.his_adapter import admit_service
    from app.services.redis_cache import redis_cache

    # ── 重发去重（规范 7.4）：厂商超时重发用同 msg_id，已处理过则幂等地再回成功 ack ──
    #
    # 去重键 = msg_id + payload 内容指纹（2026-08-15 第十轮审计修复）。
    # 原先只用 msg_id，而规范只写了「重发请保持 msg_id 不变」，没写反面
    # ——「新消息必须用新 msg_id」。厂商若把 msg_id 按 visit 生成、或图省事写死，
    # 后续**不同患者**的推送会在 10 分钟窗口内命中重复分支，我方回 code=0
    # 且把新 visit_id 原样回显，看上去完全成功，患者却根本没落库（实测证实）。
    # 加上内容指纹后：真正的超时重发（payload 逐字相同）照旧幂等；
    # 复用了 msg_id 的**新内容**则正常处理，不再静默吞掉。
    # 指纹取自解析后的 dict 做规范化序列化，与厂商的字节格式无关——
    # 对方重发时哪怕重新序列化过（键序/空格不同），仍判为同一条。
    _fingerprint = hashlib.sha256(
        json.dumps(env.payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]
    dedupe_key = f"{env.msg_id}:{_fingerprint}"
    first_time = await redis_cache.claim_nonce(
        "his_ws_msg", dedupe_key, ttl=600
    )
    if not first_time:
        logger.info("his_ws.duplicate_admit: msg_id=%s 内容相同，幂等回成功 ack",
                    env.msg_id)
        # 补 encounter_id（2026-09-01 HIS 联调失败模式审计）：规范 3.1 承诺
        # "成功 ack 的 data 含 visit_id 与 encounter_id"，正常分支两个都给，
        # 唯独这条幂等重复分支只回了 visit_id。厂商若用强类型 DTO 反序列化 data
        # 并对 encounter_id 做非空断言，**超时重发的那一次**会在他们侧抛异常——
        # 而超时重发恰恰是最需要这条 ack 正常工作的场景。
        # 按与 admit_service 相同的幂等键（visit_no + source + hospital_code）反查。
        _vid = str(env.payload.get("visit_id") or "")
        _eid = ""
        if _vid:
            from sqlalchemy import select

            from app.database import AsyncSessionLocal
            from app.models.encounter import Encounter
            with suppress(Exception):
                async with AsyncSessionLocal() as _db:
                    _rows = (await _db.execute(
                        select(Encounter).where(
                            Encounter.visit_no == _vid,
                            Encounter.status != "cancelled",
                            Encounter.his_external_ref.isnot(None),
                        ).order_by(Encounter.created_at.desc())
                    )).scalars().all()
                    _hit = next(
                        (e for e in _rows
                         if (e.his_external_ref or {}).get("source") == "admit_push"
                         and (e.his_external_ref or {}).get("hospital_code")
                         == env.payload.get("hospital_code")),
                        None,
                    )
                    _eid = _hit.id if _hit is not None else ""
        await websocket.send_text(
            wp.build_ack(env.msg_id, 0, "重复消息，此前已处理", aid, secret,
                         data={"visit_id": _vid, "encounter_id": _eid})
        )
        return
    # 失败释放 msg_id 去重占位（2026-08-11 审计修复）：claim_nonce 是「先占后处理」，
    # 若处理失败仍占着 key，厂商按规范 7.4 超时重发同 msg_id 会命中上面的重复分支拿到
    # 假成功 ack（患者其实没落库）。故所有失败分支在回错误 ack 前显式释放占位，
    # 让重发能真正重新处理（handle_admit 本身按 visit_id 幂等，重入也不会建重）。
    async def _release_and_ack(code: int, message: str) -> None:
        await redis_cache.delete(f"nonce:his_ws_msg:{dedupe_key}")
        await websocket.send_text(wp.build_ack(env.msg_id, code, message, aid, secret))

    try:
        payload = AdmitPushRequest.model_validate(env.payload)
    except ValidationError:
        await _release_and_ack(40004, wp.ERROR_TEXT[40004])
        return
    # 记录该就诊的来源连接：回写/刷新优先路由回这台诊室（它的界面才需要刷新）
    his_ws_manager.bind_visit(payload.visit_id, websocket)
    # 中断兜底（2026-08-13 第二轮审计修复）：下面的 except 只覆盖 Exception，
    # 进程重启/任务取消（CancelledError 属 BaseException）会让 msg_id 占位留着，
    # 厂商按规范重发同 msg_id 时命中重复分支拿到**假成功 ack**——接诊静默丢失。
    # 用 finally + 完成标记兜住：只要没真正处理完就释放占位，让重发能重新处理
    # （handle_admit 按 visit_id 幂等，重入不会建重）。
    completed = False
    try:
        try:
            result = await admit_service.handle_admit(payload)
        except admit_service.AdmitError as exc:
            # 业务拒收（如医生工号未注册）：错误码回 ack，厂商日志可见、便于排查
            logger.warning("his_ws.admit_rejected: visit_id=%s %s",
                           payload.visit_id, exc.message)
            await _release_and_ack(exc.code, exc.message)
            completed = True  # 已如实回错误 ack 并释放占位，无需 finally 再释放
            return
        except Exception:
            logger.exception("his_ws.admit_error: visit_id=%s", payload.visit_id)
            await _release_and_ack(50000, "服务内部错误")
            completed = True
            return
        # 日志不落患者姓名（PHI 不进日志文件），排障用 visit_id/encounter_id 关联
        logger.info("his_ws.admit: visit_id=%s encounter=%s reused=%s",
                    payload.visit_id, result.encounter_id, result.reused)
        await websocket.send_text(
            wp.build_ack(env.msg_id, 0, "success", aid, secret,
                         data={"visit_id": payload.visit_id,
                               "encounter_id": result.encounter_id})
        )
        completed = True
    finally:
        if not completed:
            # 被取消/进程收摊：释放去重占位，避免下次重发拿到假成功
            with suppress(Exception):
                await redis_cache.delete(f"nonce:his_ws_msg:{dedupe_key}")
