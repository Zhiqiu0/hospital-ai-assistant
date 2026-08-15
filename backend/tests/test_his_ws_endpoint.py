"""HIS WebSocket 路由端到端测试（TestClient 走真实握手 + 消息循环）。"""
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.his_adapter import ws_protocol as wp
from app.his_adapter.signing import compute_sign
from app.main import app

AID, SECRET = "appHIS", "secret-key"


@pytest.fixture
def ws_env(monkeypatch):
    """开保险丝 + 注入测试凭证 + 消息去重打桩（不依赖真实 Redis）。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    monkeypatch.setattr(settings, "his_inbound_app_id", AID)
    monkeypatch.setattr(settings, "his_inbound_app_secret", SECRET)

    from app.services import redis_cache as rc_module
    seen: set = set()

    async def fake_claim_nonce(scope, nonce, *, ttl):
        key = (scope, nonce)
        if key in seen:
            return False
        seen.add(key)
        return True

    monkeypatch.setattr(rc_module.redis_cache, "claim_nonce", fake_claim_nonce)

    # 业务落地（建档/派医生）由 test_his_admit_service.py 专测；这里打桩隔离 DB
    from app.his_adapter import admit_service

    async def fake_handle_admit(payload):
        return admit_service.AdmitResult(
            encounter_id="enc-test", patient_id="p-test",
            patient_name=payload.patient_name, doctor_id="d-test", reused=False,
        )

    monkeypatch.setattr(admit_service, "handle_admit", fake_handle_admit)
    return TestClient(app)


def _handshake_url(app_id=AID, secret=SECRET, sign=None, nonce=None) -> str:
    ts = str(int(time.time() * 1000))
    nonce = nonce or uuid.uuid4().hex
    sign = sign or compute_sign(app_id, ts, nonce, wp.HANDSHAKE_LITERAL, secret)
    return (f"/api/v1/his/ws?app_id={app_id}&timestamp={ts}"
            f"&nonce={nonce}&sign={sign}")


def _admit_text(visit_id="V1", msg_id=None, secret=SECRET) -> str:
    payload_raw = json.dumps(
        {"visit_id": visit_id, "hospital_code": "H1", "patient_name": "张三"},
        ensure_ascii=False)
    msg_id = msg_id or f"his-{uuid.uuid4().hex}"
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(AID, ts, nonce, payload_raw, secret)
    return ('{"type": "encounter_admit", "msg_id": "%s", "app_id": "%s", '
            '"timestamp": "%s", "nonce": "%s", "sign": "%s", "payload": %s}'
            % (msg_id, AID, ts, nonce, sign, payload_raw))


def _recv_skip_heartbeat(ws) -> wp.WsEnvelope:
    """读一条非心跳消息：CI 跑器卡顿超过 30s 时，服务端心跳 ping 可能插到
    业务应答之前，直接读一条会偶发拿到 ping 帧（CI 偶发红）。跳过即可。"""
    while True:
        env = wp.WsEnvelope.model_validate_json(ws.receive_text())
        if env.type != wp.MSG_PING:
            return env


def test_ws_admit_roundtrip(ws_env):
    """握手成功 → 发接诊推送 → 收到 code=0 的 ack（回声 visit_id）。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(visit_id="V123"))
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_ACK
        assert env.payload["code"] == 0
        assert env.payload["data"]["visit_id"] == "V123"


def test_ws_handshake_bad_sign_rejected(ws_env):
    """握手签名错误 → 连接被拒绝（无法建立会话）。"""
    with pytest.raises(Exception):
        with ws_env.websocket_connect(_handshake_url(sign="deadbeef")):
            pass


def test_ws_handshake_replay_rejected(ws_env):
    """同一握手 nonce 重放（相同 URL 再建连）→ 被防重放拦截（2026-08-11 审计延期项）。

    ws_env 的 fake_claim_nonce 用 seen 集模拟 Redis：首次 claim True、重放 False。
    """
    ts = str(int(time.time() * 1000))
    fixed_nonce = "handshake-replay-fixed"
    sign = compute_sign(AID, ts, fixed_nonce, wp.HANDSHAKE_LITERAL, SECRET)
    url = (f"/api/v1/his/ws?app_id={AID}&timestamp={ts}"
           f"&nonce={fixed_nonce}&sign={sign}")
    # 首次建连成功
    with ws_env.websocket_connect(url):
        pass
    # 同 nonce 重放 → 拒绝
    with pytest.raises(Exception):
        with ws_env.websocket_connect(url):
            pass


def test_ws_disabled_rejected(ws_env, monkeypatch):
    """保险丝关闭 → 拒绝握手。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", False)
    with pytest.raises(Exception):
        with ws_env.websocket_connect(_handshake_url()):
            pass


def test_ws_bad_message_sign_gets_40001(ws_env):
    """消息签名错误（用错密钥）→ ack code=40001。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(secret="wrong-secret"))
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_ACK and env.payload["code"] == 40001


def test_ws_ping_gets_pong(ws_env):
    """厂商 ping → 我方回 pong（心跳免验签）。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(json.dumps({"type": "ping", "msg_id": "p1"}))
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_PONG


def test_ws_duplicate_msg_id_idempotent(ws_env):
    """同 msg_id 重发（模拟厂商 ack 丢失后重试）→ 幂等地再回成功 ack。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        fixed = "his-dup-001"
        ws.send_text(_admit_text(visit_id="V9", msg_id=fixed))
        first = _recv_skip_heartbeat(ws)
        assert first.payload["code"] == 0
        ws.send_text(_admit_text(visit_id="V9", msg_id=fixed))
        second = _recv_skip_heartbeat(ws)
        assert second.payload["code"] == 0  # 不报错、不重复处理
        assert second.payload["ack_msg_id"] == fixed


def test_ws_admit_business_error_gets_40007(ws_env, monkeypatch):
    """业务拒收（医生工号未注册）→ ack code=40007，message 带具体原因。"""
    from app.his_adapter import admit_service

    async def rejecting_handle_admit(payload):
        raise admit_service.AdmitError(40007, "医生工号 D404 未在 MediScribe 注册或已停用")

    monkeypatch.setattr(admit_service, "handle_admit", rejecting_handle_admit)
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(visit_id="V404"))
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_ACK
        assert env.payload["code"] == 40007
        assert "D404" in env.payload["message"]


def test_ws_unknown_type_gets_40004(ws_env):
    """未知消息类型 → ack code=40004。"""
    payload_raw = "{}"
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(AID, ts, nonce, payload_raw, SECRET)
    text = ('{"type": "mystery", "msg_id": "m9", "app_id": "%s", '
            '"timestamp": "%s", "nonce": "%s", "sign": "%s", "payload": %s}'
            % (AID, ts, nonce, sign, payload_raw))
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(text)
        env = _recv_skip_heartbeat(ws)
        assert env.payload["code"] == 40004


def test_probe_handshake_not_logged_as_warning(ws_env, caplog):
    """无凭证探测（健康监控/端口扫描）不得写 WARNING 到 error.log。

    uptime-kuma 对 /api/v1/his/ws 的存活探测每 60 秒一次、不带任何凭证。
    若按 WARNING 记，一天 1440 条会把「error.log 只装 WARNING 以上」这个
    排障入口彻底淹掉。带了凭证但不对的仍须保持 WARNING（真实鉴权失败）。
    """
    import logging
    with caplog.at_level(logging.WARNING, logger="app.api.v1.his_ws"):
        with pytest.raises(Exception):
            with ws_env.websocket_connect("/api/v1/his/ws"):  # 一个参数都不带
                pass
    assert not [r for r in caplog.records if "handshake_rejected" in r.message], \
        "无凭证探测不应产生 WARNING"

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.api.v1.his_ws"):
        with pytest.raises(Exception):
            with ws_env.websocket_connect(_handshake_url(sign="deadbeef")):
                pass
    assert [r for r in caplog.records if "handshake_rejected" in r.message], \
        "带凭证但签名错属真实鉴权失败，必须保留 WARNING"


# ── 2026-08-15 第十轮审计（实现者视角 + 故障注入）新增回归 ────────────────────

def test_ws_binary_frame_accepted(ws_env):
    """二进制帧承载的同一条 JSON 也要收下，不能因此断连。

    厂商客户端多为 C#/Java，其 WebSocket API 要显式指定 Text/Binary，
    选成 Binary 是很常见的笔误。修复前 receive_text() 会抛 KeyError('text')，
    被消息循环当成连接层错误 → 整条连接断开：厂商侧表现为「握手成功但一发
    消息就断线」并无限重连，没有 ack、没有错误码，我方日志也只有一句
    connection_error: 'text'，两边都无从定位。
    """
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_bytes(_admit_text(visit_id="V-BIN").encode("utf-8"))
        env = _recv_skip_heartbeat(ws)
        assert env.type == wp.MSG_ACK
        assert env.payload["code"] == 0
        assert env.payload["data"]["visit_id"] == "V-BIN"


def _admit_text_without_msg_id(visit_id="V1") -> str:
    """构造一条漏了信封 msg_id 的业务消息（其余字段与签名都合法）。"""
    payload_raw = json.dumps(
        {"visit_id": visit_id, "hospital_code": "H1", "patient_name": "张三"},
        ensure_ascii=False)
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(AID, ts, nonce, payload_raw, SECRET)
    return ('{"type": "encounter_admit", "app_id": "%s", "timestamp": "%s", '
            '"nonce": "%s", "sign": "%s", "payload": %s}'
            % (AID, ts, nonce, sign, payload_raw))


def test_ws_business_msg_without_msg_id_gets_40004(ws_env):
    """信封缺必填项的业务消息 → 明确回 40004 并点名字段，不再静默丢弃。

    静默丢弃是最难定位的一类故障（第九轮「ack 漏签名」已证实）：
    厂商日志显示「我发了」，我方毫无反应，双方都看不出问题在哪。
    """
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text_without_msg_id())
        env = _recv_skip_heartbeat(ws)
        assert env.payload["code"] == 40004
        assert "msg_id" in env.payload["message"]


def test_ws_ack_without_own_msg_id_still_dispatched(ws_env, caplog):
    """ack 漏了自己的 msg_id 仍要被正常分发（我方只用 payload.ack_msg_id）。

    ack 自己的 msg_id 与 ack_msg_id 是两回事，厂商很容易只写后者。修复前
    整条 ack 在信封解析处就被丢掉，我方等不到应答 → 重发 3 次 → 判连接失效
    断开 → 换线重来，而厂商日志里明明写着「我回过 ack」。
    这里用一个无人等待的 ack_msg_id：能走到 orphan_ack 就证明它进了分发链路，
    而不是在解析阶段被扔掉；同时确认我方不会对 ack 回任何消息。
    """
    import logging
    payload_raw = json.dumps({"code": 0, "message": "success",
                              "ack_msg_id": "ms-nobody-waits"}, ensure_ascii=False)
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sign = compute_sign(AID, ts, nonce, payload_raw, SECRET)
    ack_text = ('{"type": "ack", "app_id": "%s", "timestamp": "%s", "nonce": "%s", '
                '"sign": "%s", "payload": %s}' % (AID, ts, nonce, sign, payload_raw))
    with caplog.at_level(logging.WARNING, logger="app.api.v1.his_ws"):
        with ws_env.websocket_connect(_handshake_url()) as ws:
            ws.send_text(ack_text)
            ws.send_text(_admit_text(visit_id="V-AFTER-ACK"))
            env = _recv_skip_heartbeat(ws)
            # 若那条 ack 被回了消息，这里读到的第一条就不是业务 ack 了
            assert env.payload["code"] == 0
            assert env.payload["data"]["visit_id"] == "V-AFTER-ACK"
    assert [r for r in caplog.records if "orphan_ack" in r.message], \
        "缺 msg_id 的 ack 应进入分发链路（表现为 orphan_ack），而不是解析阶段被丢弃"


def test_ws_reused_msg_id_with_new_patient_not_swallowed(ws_env):
    """复用 msg_id 推**另一位患者**必须照常处理，不能当成重发静默吞掉。

    规范只写了「重发请保持 msg_id 不变」，没写反面。厂商若把 msg_id 按 visit
    生成或干脆写死，修复前第二位患者会命中 msg_id 去重分支，拿到 code=0 且
    回显其 visit_id 的成功 ack——看着完全成功，人却根本没进系统。
    现在去重键带 payload 内容指纹：内容相同才算重发。
    """
    handled: list[str] = []
    from app.his_adapter import admit_service

    async def recording_handle_admit(payload):
        handled.append(payload.visit_id)
        return admit_service.AdmitResult(
            encounter_id="enc-" + payload.visit_id, patient_id="p",
            patient_name=payload.patient_name, doctor_id="d", reused=False,
        )

    admit_service.handle_admit = recording_handle_admit  # fixture 已 monkeypatch 过
    fixed = "his-fixed-msgid"
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(visit_id="V-P1", msg_id=fixed))
        assert _recv_skip_heartbeat(ws).payload["code"] == 0
        ws.send_text(_admit_text(visit_id="V-P2", msg_id=fixed))
        assert _recv_skip_heartbeat(ws).payload["code"] == 0
    assert handled == ["V-P1", "V-P2"], f"第二位患者被吞掉了：{handled}"


# ── WS 来源 IP 白名单（2026-08-15，规范 2.2「可叠加 IP 白名单」）──────────────

def test_ip_allowlist_empty_means_no_restriction(ws_env):
    """默认留空 = 不限制：与加此功能之前行为完全一致（零回归）。"""
    with ws_env.websocket_connect(_handshake_url()) as ws:
        ws.send_text(_admit_text(visit_id="V-NOLIST"))
        assert _recv_skip_heartbeat(ws).payload["code"] == 0


def test_ip_allowlist_blocks_outsider(ws_env, monkeypatch):
    """白名单开启后，名单外的来源在验签之前就被拒。"""
    monkeypatch.setattr(settings, "his_ws_ip_allowlist", "203.0.113.0/29")
    with pytest.raises(Exception):
        with ws_env.websocket_connect(
            _handshake_url(), headers={"X-Real-IP": "198.51.100.9"}
        ):
            pass


def test_ip_allowlist_allows_listed_cidr(ws_env, monkeypatch):
    """名单内的来源（含 CIDR 网段）正常放行。"""
    monkeypatch.setattr(settings, "his_ws_ip_allowlist", "203.0.113.0/29,192.0.2.5")
    for ip in ("203.0.113.3", "192.0.2.5"):
        with ws_env.websocket_connect(
            _handshake_url(), headers={"X-Real-IP": ip}
        ) as ws:
            ws.send_text(_admit_text(visit_id="V-OK-" + ip))
            assert _recv_skip_heartbeat(ws).payload["code"] == 0


def test_ip_allowlist_not_bypassable_via_forged_xff(ws_env, monkeypatch):
    """伪造 X-Forwarded-For 首段不能绕过白名单。

    生产 nginx 用的是 `X-Forwarded-For $proxy_add_x_forwarded_for`——客户端
    自带的 XFF 会被原样保留在**前面**、真实地址追加在末尾。若按首段判定，
    攻击者只要发一个 `X-Forwarded-For: <医院出口IP>` 就能长驱直入，
    白名单形同虚设。判定必须取 nginx 无条件覆盖写入的 X-Real-IP。
    """
    monkeypatch.setattr(settings, "his_ws_ip_allowlist", "203.0.113.7")
    with pytest.raises(Exception):
        with ws_env.websocket_connect(_handshake_url(), headers={
            "X-Forwarded-For": "203.0.113.7, 198.51.100.9",  # 首段是伪造的
            "X-Real-IP": "198.51.100.9",                      # nginx 写的真实地址
        }):
            pass


def test_ip_allowlist_malformed_config_fails_at_startup():
    """白名单写错一个字符 = 全院连不上，必须启动期就报错而不是运行期才发现。"""
    from app.config import Settings
    s = Settings(his_adapter_enabled=True, his_inbound_app_id="a",
                 his_inbound_app_secret="b", his_ws_ip_allowlist="203.0.113.7,不是IP")
    with pytest.raises(ValueError, match="HIS_WS_IP_ALLOWLIST"):
        s.validate_runtime()
