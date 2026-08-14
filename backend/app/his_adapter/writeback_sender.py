"""病历回写发送：组装 payload → 按通道下发（写入 + 刷新），带超时与重试。

通道选择（规范第 7 章）：HIS WebSocket 长连接在线时优先走方案 B（消息下行 + ack）；
离线时回落方案 A（HTTP POST 签名调用）；两者均不可用返回 skipped 安全空跑。

依赖配置（待厂商确认后填，见 config.py）：
  his_writeback_url / his_writeback_refresh_url / his_writeback_app_id /
  his_writeback_app_secret / his_writeback_timeout_seconds / his_writeback_max_retries

设计要点：
  - 回写地址未配置时直接返回 skipped（不报错），便于联调前空跑、上线前安全。
  - 签名方向：我方调 HIS，用 HIS 分配给我方的 his_writeback_app_* 凭证签名。
  - body_raw 固定序列化一次，签名与发送用同一份；重试时只换 timestamp/nonce/sign。
  - 写入成功后再调刷新（刷新地址未配置则跳过，由 HIS 自动刷新场景兼容）。
"""
import json
import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.his_adapter import ws_protocol as wp
from app.his_adapter.signing import compute_sign
from app.his_adapter.writeback_builder import build_writeback_payload
from app.his_adapter.ws_manager import his_ws_manager


@dataclass
class WritebackResult:
    """回写结果。status: success | skipped | write_failed | refresh_failed。"""

    ok: bool
    status: str
    message: str = ""
    his_doc_id: Optional[str] = None
    http_status: Optional[int] = None


def _signed_headers(body_raw: str, request_id: str) -> dict:
    """按规范给回写请求生成签名头（每次调用换新的 timestamp/nonce）。

    request_id 是**请求级幂等键**，与 timestamp/nonce 相反——它在整条重试链路上
    保持不变（2026-08-14 第八轮审计）：
      原先整条 HTTP 回写没有任何幂等键。HIS 处理慢导致 30s 读超时时（写入与刷新
      各 30s，很容易触发），HIS 其实已经把病历落库了，我方判为失败立刻原样重发，
      病案里就多一份；后面对账任务还会最多再重投 5 次，每次都是全新 nonce，
      HIS 无从判重。项目自己在 reconcile 与 event_bus 的注释里反复强调
      「重复回写 = 病案里出现两份病历」，发送侧却从未提供让 HIS 去重的手段。
      WS 通道用的是 msg_id，HTTP 这条对应下来就是这个头。
    """
    app_id = settings.his_writeback_app_id
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(app_id, ts, nonce, body_raw, settings.his_writeback_app_secret)
    return {
        "X-App-Id": app_id,
        "X-Timestamp": ts,
        "X-Nonce": nonce,
        "X-Sign": sign,
        # 幂等键：同一份病历的所有重试（含对账重投）共用同一个值
        "X-Request-Id": request_id,
        "Content-Type": "application/json; charset=utf-8",
    }


# 5xx 重试的退避基数（秒）。原先是裸 continue，3 次重试在毫秒内打完——
# 对一台正在重启的 HIS 毫无意义，只是把重复写入的概率乘 3。
_RETRY_BACKOFF_BASE = 1.0


async def _post_with_retry(
    client: httpx.AsyncClient, url: str, body_raw: str, max_retries: int,
    *, request_id: Optional[str] = None,
) -> httpx.Response:
    """POST body_raw 到 url；网络异常或 5xx 时重试，最多 max_retries 次。

    request_id 贯穿整条重试链路不变，供 HIS 侧去重（见 _signed_headers）。
    """
    # 调用方不传时就地生成：保证「同一次 _post_with_retry 的所有重试」同键
    req_id = request_id or uuid.uuid4().hex
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = await client.post(
                url, content=body_raw.encode("utf-8"),
                headers=_signed_headers(body_raw, req_id),
            )
            if resp.status_code >= 500 and attempt < max_retries:
                # 指数退避：给对面重启/过载留出恢复时间
                await asyncio.sleep(_RETRY_BACKOFF_BASE * (2 ** attempt))
                continue
            return resp
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            await asyncio.sleep(_RETRY_BACKOFF_BASE * (2 ** attempt))
    # 理论不可达：循环要么 return 要么 raise
    raise last_exc  # type: ignore[misc]


def _envelope_code(resp: httpx.Response) -> tuple[int, str, dict]:
    """解析 HIS 返回的统一信封，返回 (code, message, data)；非 JSON 视为失败。"""
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        return -1, "响应非 JSON", {}
    code = body.get("code", -1)
    try:
        code = int(code)
    except (ValueError, TypeError):
        code = -1
    return code, str(body.get("message", "")), (body.get("data") or {})


async def send_writeback(
    db: AsyncSession,
    encounter_id: str,
    app_version: str = "1.0.0",
    client: Optional[httpx.AsyncClient] = None,
) -> WritebackResult:
    """把一次接诊的病历回写到 HIS（写入 + 刷新），并把结果落库。

    结果持久化（2026-08-11 技术债清偿）：写进 encounter.his_external_ref 的
    writeback 键（JSONB 免加列），叫号队列据此展示"已回写/回写失败"，
    失败的可从队列一键重试（手动端点与自动派发都经过本函数，单点落库）。

    Args:
        db:           异步会话
        encounter_id: 接诊 ID
        app_version:  MediScribe 版本（写进 meta）
        client:       可注入的 httpx 客户端（测试用）；为空则内部创建

    Returns:
        WritebackResult
    """
    result = await _send_writeback_inner(db, encounter_id, app_version, client)
    await _persist_writeback_status(db, encounter_id, result)
    return result


async def _persist_writeback_status(
    db: AsyncSession, encounter_id: str, result: WritebackResult
) -> None:
    """把回写结果写进 encounter.his_external_ref.writeback（失败只记日志不影响返回）。"""
    import logging
    from datetime import datetime

    from app.models.encounter import Encounter

    try:
        encounter = await db.get(Encounter, encounter_id)
        if encounter is None or not encounter.his_external_ref:
            return
        # 对账状态必须保留（2026-08-13 复检修复）：原实现整体替换 writeback 字典，
        # 把 reconcile_attempts / reconcile_exhausted 一并抹掉——而对账流程是
        # 「先 send_writeback（计数被抹零）再 _mark_reconcile（+1）」，导致计数
        # 恒为 1、MAX_RECONCILE_ATTEMPTS 上限永不成立、耗尽告警永不触发，
        # 失败回写会被静默重投到窗口期结束。这里显式承接旧的对账字段。
        prev_wb = (encounter.his_external_ref.get("writeback") or {})
        new_wb = {
            "status": result.status,
            "ok": result.ok,
            "message": result.message,
            "his_doc_id": result.his_doc_id,
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        for keep in ("reconcile_attempts", "reconcile_exhausted"):
            if keep in prev_wb:
                new_wb[keep] = prev_wb[keep]
        # 回写成功即视为对账结束：清零计数，避免历史失败次数影响将来的重投判定
        if result.ok:
            new_wb.pop("reconcile_attempts", None)
            new_wb.pop("reconcile_exhausted", None)
        # JSONB 整体重赋值才会被 SQLAlchemy 侦测为脏（未挂 MutableDict）
        encounter.his_external_ref = {
            **encounter.his_external_ref,
            "writeback": new_wb,
        }
        await db.commit()
    except Exception:
        logging.getLogger(__name__).exception(
            "his_wb.persist: 回写状态落库失败 encounter=%s", encounter_id)


async def _send_writeback_inner(
    db: AsyncSession,
    encounter_id: str,
    app_version: str = "1.0.0",
    client: Optional[httpx.AsyncClient] = None,
) -> WritebackResult:
    """回写主流程（通道选择 + 写入 + 刷新），结果由外层 send_writeback 落库。"""
    payload = await build_writeback_payload(db, encounter_id, app_version=app_version)
    # 连接池护栏（2026-08-11 审计修复）：payload 已读完，后面等 WS ack 最长可达 ~80s
    # （10s×3 重发 ×2 条消息），这期间不该占着 asyncpg 连接。提交只读事务把连接还池，
    # 与 qc_stream_service 的既有护栏一致；外层 _persist_writeback_status 会另起短事务落库。
    # （db 为 None 仅出现在 WS 通道单测里 mock 掉 payload 构建的场景，生产恒为真实会话）
    if db is not None:
        await db.commit()

    # 通道选择：WS 长连接在线 → 方案 B；否则有 HTTP 地址 → 方案 A；都没有 → 空跑
    if his_ws_manager.has_connection():
        return await _send_via_ws(payload)
    if not settings.his_writeback_url:
        return WritebackResult(ok=False, status="skipped", message="回写地址未配置且 WS 未连接")
    body_raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    max_retries = settings.his_writeback_max_retries

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.his_writeback_timeout_seconds)
    try:
        # ── 确定性幂等键（2026-08-14 第八轮审计）────────────────────────────
        # 用规范 §2.5 定义的那三段拼，而不是随机 uuid：这样不仅本次调用的
        # 3 次重试同键，**几小时后对账任务的重投也是同一个键**——那才是重复
        # 写入的主要来源（MAX_RECONCILE_ATTEMPTS=5，每次都是全新 nonce）。
        req_id = "wb-{}-{}-{}".format(
            payload.get("visit_id") or "", payload.get("record_type") or "",
            payload.get("record_no") if payload.get("record_no") is not None else "0",
        )

        # 1. 写入
        try:
            resp = await _post_with_retry(
                client, settings.his_writeback_url, body_raw, max_retries,
                request_id=req_id,
            )
        except httpx.HTTPError as exc:
            return WritebackResult(ok=False, status="write_failed", message=f"网络异常：{exc}")
        if resp.status_code != 200:
            return WritebackResult(
                ok=False, status="write_failed",
                message=f"HTTP {resp.status_code}", http_status=resp.status_code,
            )
        code, message, data = _envelope_code(resp)
        if code != 0:
            return WritebackResult(
                ok=False, status="write_failed",
                message=f"HIS 返回 code={code} {message}", http_status=200,
            )
        his_doc_id = data.get("record_id") or data.get("doc_id") or data.get("id")

        # 2. 刷新（刷新地址未配置则跳过）
        if settings.his_writeback_refresh_url:
            # target 直接用 record_type（2026-08-14 第六轮审计修复）：
            # 原先硬拼 f"{record_type}_record"，门诊拼出 outpatient_record 尚可，
            # 住院则拼成 admission_note_record / course_record_record 这类非法值。
            # record_type 本身就是规范附录里与厂商对齐过的枚举
            # （outpatient/emergency/admission_note/course_record/discharge_record/
            # op_record...），直接下发最可靠。
            target = payload["record_type"]
            refresh_raw = json.dumps(
                {"visit_id": payload["visit_id"], "target": target},
                ensure_ascii=False, sort_keys=True,
            )
            try:
                rresp = await _post_with_retry(
                    client, settings.his_writeback_refresh_url, refresh_raw, max_retries,
                    # 刷新是同一次回写的第二个动作，键上加后缀区分
                    request_id=f"{req_id}:refresh",
                )
            except httpx.HTTPError as exc:
                return WritebackResult(
                    ok=False, status="refresh_failed",
                    message=f"刷新网络异常：{exc}", his_doc_id=his_doc_id,
                )
            if rresp.status_code != 200:
                return WritebackResult(
                    ok=False, status="refresh_failed",
                    message=f"刷新 HTTP {rresp.status_code}", his_doc_id=his_doc_id,
                )

        return WritebackResult(ok=True, status="success", his_doc_id=his_doc_id, http_status=200)
    finally:
        if own_client:
            await client.aclose()


async def _send_via_ws(payload: dict) -> WritebackResult:
    """方案 B：经 HIS 长连接下发回写（写入 + 刷新），以 ack 的 code 判定成败。

    ack 超时重发由 ws_manager 负责（10s×3，规范 7.4）；耗尽或断线抛 ConnectionError。
    方案 B 凭证只有一套：双向均用 his_inbound_app_id/secret 签名。
    """
    aid, secret = settings.his_inbound_app_id, settings.his_inbound_app_secret

    # 1. 写入（prefer_visit：优先发回该就诊的接诊来源诊室，见 ws_manager 路由规则）
    try:
        ack = await his_ws_manager.send_with_ack(
            wp.MSG_WRITEBACK, payload, aid, secret, prefer_visit=payload["visit_id"])
    except ConnectionError as exc:
        return WritebackResult(ok=False, status="write_failed", message=f"WS 发送失败：{exc}")
    code = ack.get("code", -1)
    if code != 0:
        return WritebackResult(
            ok=False, status="write_failed",
            message=f"HIS 返回 code={code} {ack.get('message', '')}",
        )
    data = ack.get("data") or {}
    his_doc_id = data.get("record_id") or data.get("doc_id") or data.get("id")

    # 2. 刷新（与 HTTP 通道语义一致：写入成功后必须刷新，失败标记 refresh_failed）
    refresh_payload = {
        "visit_id": payload["visit_id"],
        # 同 HTTP 通道：直接用 record_type，不再硬拼 "_record" 后缀
        "target": payload["record_type"],
    }
    try:
        rack = await his_ws_manager.send_with_ack(
            wp.MSG_REFRESH, refresh_payload, aid, secret, prefer_visit=payload["visit_id"])
    except ConnectionError as exc:
        return WritebackResult(
            ok=False, status="refresh_failed",
            message=f"刷新 WS 发送失败：{exc}", his_doc_id=his_doc_id,
        )
    if rack.get("code", -1) != 0:
        return WritebackResult(
            ok=False, status="refresh_failed",
            message=f"刷新 HIS 返回 code={rack.get('code')}", his_doc_id=his_doc_id,
        )
    return WritebackResult(ok=True, status="success", his_doc_id=his_doc_id)
