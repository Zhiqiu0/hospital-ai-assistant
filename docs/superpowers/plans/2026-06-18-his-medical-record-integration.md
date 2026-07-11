# HIS 病历对接（接诊推送接收 + 病历回写组装）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/MediScribe_HIS接口规范.docx` 实现「我方自己说了算、不依赖厂商」的后端部分：HMAC 签名工具、统一响应信封、接诊推送接收接口、病历回写 payload 组装。回写"往哪发/怎么认证"做成配置占位，等厂商确认。

**Architecture:** 全部代码落在 `backend/app/his_adapter/`（HIS 适配层，与 SaaS 隔离）+ 新增路由 `backend/app/api/v1/his.py`，整体受 `HIS_ADAPTER_ENABLED` 保险丝保护（关闭即 503，不影响 SaaS）。接诊推送（HIS→我方）用 HMAC 签名鉴权（非 JWT）；回写 payload 从现有 `InquiryInput`（分字段）+ `RecordVersion`（全文）组装，不动核心库表。

**Tech Stack:** FastAPI / SQLAlchemy async / Pydantic v2 / pytest + pytest-asyncio / HMAC-SHA256（hmac+hashlib 标准库）。

**本计划范围内不做（依赖厂商或待定设计，明确排除）：**
- 回写的真正 HTTP 发送 + 刷新调用 + 重试（需厂商回 附录 B：回写地址/鉴权/是否公网可达）→ 仅留配置项与 builder，发送另起计划。
- 接诊推送与 embed/start 的 encounter/医生归属联动、桌面 Agent 自动拉起 → 设计待定，本期接诊接收只做「验签 + 患者同步 + ACK」，不建 encounter（encounter 仍由现有 embed/start 创建）。
- 住院专属字段、record_no 多文书拆分 → 结构已在文档预留，后续按向后兼容补。
- 可选的"回写状态"库表字段 → 不在本期。

---

## 文件结构

| 文件 | 创建/修改 | 职责 |
|---|---|---|
| `backend/app/config.py` | 修改 | 新增接诊验签密钥 + 回写目标/凭证配置占位 |
| `backend/app/his_adapter/signing.py` | 创建 | HMAC-SHA256 签名/验签/时间戳校验 |
| `backend/app/his_adapter/models.py` | 修改 | 新增 `ApiEnvelope`、`ok()/err()`、`AdmitPushRequest` |
| `backend/app/his_adapter/writeback_builder.py` | 创建 | encounter_id → 回写 payload dict |
| `backend/app/api/v1/his.py` | 创建 | `POST /his/encounter/admit` 接诊推送接收 |
| `backend/app/api/v1/__init__.py` | 修改 | 注册 his.router |
| `backend/tests/test_his_signing.py` | 创建 | 签名工具单测 |
| `backend/tests/test_his_writeback_builder.py` | 创建 | 回写组装单测 |
| `backend/tests/test_his_admit.py` | 创建 | 接诊接收接口单测 |

**测试命令（统一）：** `cd backend && venv/Scripts/python.exe -m pytest <file> -v`

---

## Task 1: 新增配置项（签名密钥 + 回写占位）

**Files:**
- Modify: `backend/app/config.py`（在 `his_embed_token_ttl_hours: int = 4` 之后插入）

- [ ] **Step 1: 加配置项**

在 `backend/app/config.py` 的 `Settings` 类里，紧接 `his_embed_token_ttl_hours: int = 4` 这一行之后，加入：

```python
    # ── HIS 接诊推送验签（HIS→我方）──────────────────────────────
    # 我方分配给 HIS 的一对凭证，用于验证 HIS 接诊推送的 HMAC 签名
    his_inbound_app_id: str = ""
    his_inbound_app_secret: str = ""
    # 签名时间戳允许误差（秒），防重放，默认 5 分钟
    his_sign_clock_skew_seconds: int = 300
    # ── HIS 病历回写（我方→HIS，待厂商确认后填，先占位）──────────
    his_writeback_url: str = ""           # 回写写入接口地址
    his_writeback_refresh_url: str = ""   # 触发前端刷新接口地址
    his_writeback_app_id: str = ""        # HIS 分配给我方的凭证
    his_writeback_app_secret: str = ""
    his_writeback_timeout_seconds: int = 30
```

- [ ] **Step 2: 验证导入不报错**

Run: `cd backend && venv/Scripts/python.exe -c "from app.config import settings; print(settings.his_inbound_app_id, settings.his_sign_clock_skew_seconds)"`
Expected: 输出 ` 300`（空字符串 + 300），无异常

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(his): 新增接诊验签与病历回写配置项"
```

---

## Task 2: HMAC 签名工具

**Files:**
- Create: `backend/app/his_adapter/signing.py`
- Test: `backend/tests/test_his_signing.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_his_signing.py`：

```python
"""HIS 签名工具单测。"""
import time

from app.his_adapter.signing import compute_sign, verify_sign, timestamp_fresh


def test_compute_sign_deterministic():
    """同样入参算出同样签名，且为 64 位十六进制。"""
    sig = compute_sign("appA", "1700000000000", "n1", '{"a":1}', "secret")
    assert sig == compute_sign("appA", "1700000000000", "n1", '{"a":1}', "secret")
    assert len(sig) == 64 and all(c in "0123456789abcdef" for c in sig)


def test_verify_sign_pass_and_fail():
    """正确签名通过，篡改任一项失败。"""
    args = ("appA", "1700000000000", "n1", '{"a":1}', "secret")
    sig = compute_sign(*args)
    assert verify_sign("appA", "1700000000000", "n1", '{"a":1}', sig, "secret") is True
    # 篡改 body
    assert verify_sign("appA", "1700000000000", "n1", '{"a":2}', sig, "secret") is False
    # 错密钥
    assert verify_sign("appA", "1700000000000", "n1", '{"a":1}', sig, "wrong") is False


def test_timestamp_fresh():
    """当前时间戳通过，超出误差或非法失败。"""
    now_ms = str(int(time.time() * 1000))
    assert timestamp_fresh(now_ms, 300) is True
    old_ms = str(int((time.time() - 600) * 1000))
    assert timestamp_fresh(old_ms, 300) is False
    assert timestamp_fresh("not-a-number", 300) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_signing.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.his_adapter.signing'`

- [ ] **Step 3: 写实现**

创建 `backend/app/his_adapter/signing.py`：

```python
"""HIS 对接 HMAC-SHA256 签名工具（接诊推送验签 / 病历回写签名）。

签名算法（与《MediScribe×HIS 接口规范》一致）：
    待签串 = app_id + timestamp + nonce + body_raw（请求体原文）
    sign   = hex( HMAC_SHA256(app_secret, 待签串) )
"""
import hashlib
import hmac
import time


def compute_sign(app_id: str, timestamp: str, nonce: str, body_raw: str, app_secret: str) -> str:
    """按规范拼串并算 HMAC-SHA256，返回 64 位十六进制签名。"""
    message = f"{app_id}{timestamp}{nonce}{body_raw}"
    return hmac.new(
        app_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_sign(
    app_id: str, timestamp: str, nonce: str, body_raw: str, provided_sign: str, app_secret: str
) -> bool:
    """常数时间比对签名（防时序攻击）。provided_sign 为空一律 False。"""
    expected = compute_sign(app_id, timestamp, nonce, body_raw, app_secret)
    return hmac.compare_digest(expected, provided_sign or "")


def timestamp_fresh(timestamp: str, skew_seconds: int) -> bool:
    """校验 13 位毫秒时间戳是否在允许误差内（防重放）；非法时间戳返回 False。"""
    try:
        ts = int(timestamp) / 1000.0
    except (ValueError, TypeError):
        return False
    return abs(time.time() - ts) <= skew_seconds
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_signing.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/his_adapter/signing.py backend/tests/test_his_signing.py
git commit -m "feat(his): HMAC-SHA256 签名/验签工具 + 单测"
```

---

## Task 3: 统一响应信封 + 接诊推送请求模型

**Files:**
- Modify: `backend/app/his_adapter/models.py`（在文件末尾追加）
- Test: `backend/tests/test_his_writeback_builder.py`（本 Task 仅加一个信封小测，builder 测试在 Task 4 补全；也可单列，这里合并到 builder 测试文件的顶部）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_his_writeback_builder.py`（先放信封 + 模型的测试，Task 4 再往里加 builder 测试）：

```python
"""HIS 响应信封 / 接诊推送模型 / 回写组装 单测。"""
from app.his_adapter.models import ApiEnvelope, ok, err, AdmitPushRequest


def test_envelope_ok_and_err():
    e = ok({"patient_id": "p1"}, trace_id="t1")
    assert e.code == 0 and e.message == "success" and e.data == {"patient_id": "p1"} and e.trace_id == "t1"
    e2 = err(40001, "签名校验失败")
    assert e2.code == 40001 and e2.message == "签名校验失败" and e2.data == {}


def test_admit_request_minimal_required():
    """visit_id/hospital_code/patient_name 必填，其余可空（容错向后兼容）。"""
    req = AdmitPushRequest.model_validate(
        {"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"}
    )
    assert req.visit_id == "V1" and req.gender == "unknown" and req.doctor_code is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_writeback_builder.py -v`
Expected: FAIL，`ImportError: cannot import name 'ApiEnvelope'`

- [ ] **Step 3: 写实现**

在 `backend/app/his_adapter/models.py` **文件末尾**追加（文件顶部已 `from pydantic import BaseModel, Field`，`from typing import Optional, Literal` 已在用；如缺则补 import）：

```python
class ApiEnvelope(BaseModel):
    """HIS 对接统一响应信封：{code, message, trace_id, data}。"""
    code: int = 0
    message: str = "success"
    trace_id: str = ""
    data: dict = Field(default_factory=dict)


def ok(data: Optional[dict] = None, trace_id: str = "") -> ApiEnvelope:
    """成功信封。"""
    return ApiEnvelope(code=0, message="success", trace_id=trace_id, data=data or {})


def err(code: int, message: str, trace_id: str = "") -> ApiEnvelope:
    """失败信封（HTTP 仍 200，靠 code 区分）。"""
    return ApiEnvelope(code=code, message=message, trace_id=trace_id, data={})


class AdmitPushRequest(BaseModel):
    """接诊推送请求体（HIS→我方）。visit_id/hospital_code/patient_name 必填，其余容错可空。"""
    visit_id: str
    hospital_code: str
    patient_name: str
    gender: Literal["male", "female", "unknown"] = "unknown"
    birth_date: Optional[str] = None
    id_card: Optional[str] = None
    phone: Optional[str] = None
    dept_code: Optional[str] = None
    dept_name: Optional[str] = None
    doctor_code: Optional[str] = None
    doctor_name: Optional[str] = None
    visit_type: Optional[str] = None
    is_first_visit: Optional[bool] = None
    agent_device_ip: Optional[str] = None
    agent_device_mac: Optional[str] = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_writeback_builder.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/his_adapter/models.py backend/tests/test_his_writeback_builder.py
git commit -m "feat(his): 统一响应信封 + 接诊推送请求模型"
```

---

## Task 4: 病历回写 payload 组装

**Files:**
- Create: `backend/app/his_adapter/writeback_builder.py`
- Test: `backend/tests/test_his_writeback_builder.py`（追加 builder 测试）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/test_his_writeback_builder.py` **末尾**追加（用现有 `async_db` fixture，见 `tests/conftest.py`）：

```python
import pytest
from datetime import date
from app.models.patient import Patient
from app.models.encounter import Encounter, InquiryInput
from app.his_adapter.writeback_builder import build_writeback_payload


@pytest.mark.asyncio
async def test_build_writeback_payload(async_db):
    # 造患者 + 接诊（带 HIS 标识）+ 问诊
    p = Patient(name="李四", birth_date=date(1990, 5, 1))
    async_db.add(p)
    await async_db.commit()
    enc = Encounter(
        patient_id=p.id, doctor_id="doc-1", visit_type="outpatient",
        visit_no="V20260518001", status="in_progress",
        his_external_ref={"his_brand": "jinsuanpan", "hospital_code": "H1",
                          "his_patient_no": "PNO1", "his_visit_no": "V20260518001",
                          "his_doctor_no": "D001"},
    )
    async_db.add(enc)
    await async_db.commit()
    inq = InquiryInput(
        encounter_id=enc.id, version=1,
        chief_complaint="咳嗽3天", history_present_illness="受凉后咳嗽……",
        temperature="38.5", bp_systolic="120", bp_diastolic="80",
        western_diagnosis="急性支气管炎", tongue_coating="舌红苔黄",
    )
    async_db.add(inq)
    await async_db.commit()

    payload = await build_writeback_payload(async_db, enc.id, app_version="1.0.0")

    assert payload["visit_id"] == "V20260518001"
    assert payload["record_type"] == "outpatient"
    assert payload["is_tcm"] is True               # 有舌象 → 中医
    assert payload["status"] == "draft"
    assert payload["record"]["chief_complaint"] == "咳嗽3天"
    assert "history_informant" not in payload["record"]   # 空字段不下发
    assert payload["vitals"] == {"temperature": "38.5", "bp_systolic": "120", "bp_diastolic": "80"}
    assert payload["diagnoses"] == [
        {"name": "急性支气管炎", "is_primary": True, "category": "western"}
    ]
    assert payload["meta"]["source"] == "mediscribe_ai"
    assert payload["meta"]["doctor_code"] == "D001"


@pytest.mark.asyncio
async def test_build_writeback_payload_emergency(async_db):
    """visit_type=emergency → record_type=emergency。"""
    p = Patient(name="王五", birth_date=date(1985, 1, 1))
    async_db.add(p)
    await async_db.commit()
    enc = Encounter(
        patient_id=p.id, doctor_id="doc-1", visit_type="emergency",
        visit_no="E1", status="in_progress",
        his_external_ref={"hospital_code": "H1", "his_patient_no": "P2", "his_visit_no": "E1"},
    )
    async_db.add(enc)
    await async_db.commit()
    payload = await build_writeback_payload(async_db, enc.id)
    assert payload["record_type"] == "emergency"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_writeback_builder.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.his_adapter.writeback_builder'`

- [ ] **Step 3: 写实现**

创建 `backend/app/his_adapter/writeback_builder.py`：

```python
"""把一次接诊的病历组装成 HIS 回写 payload。

数据来源：
  - Encounter.his_external_ref / visit_no / visit_type → 关联键、病历类型
  - 最新 InquiryInput（分字段）→ record.* / vitals.* / diagnoses[]
  - 最新 RecordVersion.content → full_text（整段签发全文）

红线：体征为医生录入的真实值（InquiryInput 字段），AI 不编造；空字段不下发。
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encounter import Encounter, InquiryInput
from app.models.medical_record import MedicalRecord, RecordVersion

# record.* 结构化字段（门诊/急诊用；住院专属字段后续向后兼容追加）
_RECORD_FIELDS = [
    "chief_complaint", "onset_time", "history_present_illness", "past_history",
    "allergy_history", "personal_history", "current_medications", "history_informant",
    "family_history", "marital_history", "menstrual_history", "physical_exam",
    "auxiliary_exam", "tcm_inspection", "tcm_auscultation", "tongue_coating",
    "pulse_condition", "treatment_method", "treatment_plan", "followup_advice",
    "precautions", "observation_notes", "patient_disposition",
]
_VITALS_FIELDS = [
    "temperature", "pulse", "respiration", "bp_systolic", "bp_diastolic",
    "spo2", "height", "weight",
]


def _parse_record_text(content: Any) -> str:
    """RecordVersion.content → 全文（{"text":...} 取 text，纯字符串原样，其它空串）。"""
    if isinstance(content, dict):
        return content.get("text") or ""
    if isinstance(content, str):
        return content
    return ""


def _build_diagnoses(inq: Optional[InquiryInput]) -> list[dict]:
    """从三个诊断文本字段拼成 diagnoses[]；第一个非空诊断标主诊断。"""
    if inq is None:
        return []
    out: list[dict] = []
    if inq.western_diagnosis:
        out.append({"name": inq.western_diagnosis, "is_primary": True, "category": "western"})
    if inq.tcm_disease_diagnosis:
        out.append({"name": inq.tcm_disease_diagnosis, "is_primary": not out, "category": "tcm_disease"})
    if inq.tcm_syndrome_diagnosis:
        out.append({"name": inq.tcm_syndrome_diagnosis, "is_primary": not out, "category": "tcm_syndrome"})
    return out


async def build_writeback_payload(
    db: AsyncSession, encounter_id: str, app_version: str = "1.0.0"
) -> dict:
    """组装一次接诊的病历回写 payload（dict，结构见接口规范 3.2）。"""
    encounter = await db.get(Encounter, encounter_id)
    if encounter is None:
        raise ValueError(f"encounter not found: {encounter_id}")

    # 最新问诊（分字段）
    inq = (await db.execute(
        select(InquiryInput)
        .where(InquiryInput.encounter_id == encounter_id)
        .order_by(desc(InquiryInput.updated_at))
        .limit(1)
    )).scalar_one_or_none()

    # 最新病历版本全文
    row = (await db.execute(
        select(RecordVersion)
        .join(MedicalRecord, RecordVersion.medical_record_id == MedicalRecord.id)
        .where(
            MedicalRecord.encounter_id == encounter_id,
            RecordVersion.version_no == MedicalRecord.current_version,
        )
        .order_by(desc(MedicalRecord.updated_at))
        .limit(1)
    )).scalar_one_or_none()
    full_text = _parse_record_text(row.content) if row else ""

    his_ref = encounter.his_external_ref or {}
    visit_id = his_ref.get("his_visit_no") or encounter.visit_no or ""
    record_type = "emergency" if encounter.visit_type == "emergency" else "outpatient"

    record = {f: getattr(inq, f) for f in _RECORD_FIELDS if inq and getattr(inq, f, None)}
    vitals = {f: getattr(inq, f) for f in _VITALS_FIELDS if inq and getattr(inq, f, None)}
    diagnoses = _build_diagnoses(inq)
    is_tcm = bool(
        inq and (inq.tcm_disease_diagnosis or inq.tcm_syndrome_diagnosis
                 or inq.tongue_coating or inq.pulse_condition
                 or inq.tcm_inspection or inq.tcm_auscultation)
    )

    payload: dict = {
        "visit_id": visit_id,
        "record_type": record_type,
        "is_tcm": is_tcm,
        "status": "draft",
        "record": record,
        "vitals": vitals,
        "diagnoses": diagnoses,
        "full_text": full_text,
        "meta": {
            "source": "mediscribe_ai",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "doctor_code": his_ref.get("his_doctor_no") or "",
            "app_version": app_version,
        },
    }
    return payload
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_writeback_builder.py -v`
Expected: 4 passed（含 Task 3 的 2 个）

- [ ] **Step 5: Commit**

```bash
git add backend/app/his_adapter/writeback_builder.py backend/tests/test_his_writeback_builder.py
git commit -m "feat(his): 病历回写 payload 组装（分字段+体征+诊断+全文+meta）"
```

---

## Task 5: 接诊推送接收接口

**Files:**
- Create: `backend/app/api/v1/his.py`
- Modify: `backend/app/api/v1/__init__.py`
- Test: `backend/tests/test_his_admit.py`

> 本期接诊接收只做「验签 + 校验载荷 + ACK（回声 visit_id）」，**不建患者/接诊**——患者与接诊仍由现有 `/embed/start` 负责。接诊推送与 embed/start 的联动（按 visit_no 关联、医生归属、Agent 自动拉起）属待定设计，见本计划开头"范围内不做"。本 Task 先把**签名通道**建好、可联调。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_his_admit.py`：

```python
"""接诊推送接收接口单测。"""
import json
import time

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.his_adapter.signing import compute_sign
from app.main import app


@pytest_asyncio.fixture
async def his_client(monkeypatch):
    """开启保险丝 + 注入测试验签凭证。"""
    monkeypatch.setattr(settings, "his_adapter_enabled", True)
    monkeypatch.setattr(settings, "his_inbound_app_id", "appHIS")
    monkeypatch.setattr(settings, "his_inbound_app_secret", "secret-key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _headers(body_raw: str, app_id="appHIS", secret="secret-key", ts=None):
    ts = ts or str(int(time.time() * 1000))
    nonce = "n-123"
    sign = compute_sign(app_id, ts, nonce, body_raw, secret)
    return {"X-App-Id": app_id, "X-Timestamp": ts, "X-Nonce": nonce,
            "X-Sign": sign, "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_admit_valid(his_client):
    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    res = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=_headers(body))
    assert res.status_code == 200
    j = res.json()
    assert j["code"] == 0 and j["data"]["visit_id"] == "V1"


@pytest.mark.asyncio
async def test_admit_bad_sign(his_client):
    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    headers = _headers(body)
    headers["X-Sign"] = "deadbeef"
    res = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=headers)
    assert res.json()["code"] == 40001


@pytest.mark.asyncio
async def test_admit_stale_timestamp(his_client):
    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    old_ts = str(int((time.time() - 1000) * 1000))
    res = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=_headers(body, ts=old_ts))
    assert res.json()["code"] == 40002


@pytest.mark.asyncio
async def test_admit_wrong_appid(his_client):
    body = json.dumps({"visit_id": "V1", "hospital_code": "H1", "patient_name": "张三"})
    res = await his_client.post("/api/v1/his/encounter/admit", content=body, headers=_headers(body, app_id="bad"))
    assert res.json()["code"] == 40003
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_admit.py -v`
Expected: FAIL（404 或路由不存在 / 导入失败）

- [ ] **Step 3: 写接口实现**

创建 `backend/app/api/v1/his.py`：

```python
"""HIS 对接外部接口（接诊推送接收等），HMAC 签名鉴权，受保险丝保护。"""
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.config import settings
from app.his_adapter.depends import require_his_enabled
from app.his_adapter.models import AdmitPushRequest, ApiEnvelope, err, ok
from app.his_adapter.signing import timestamp_fresh, verify_sign

router = APIRouter(
    prefix="/his",
    tags=["HIS对接"],
    dependencies=[Depends(require_his_enabled)],  # 全局保险丝
)


@router.post("/encounter/admit", response_model=ApiEnvelope)
async def admit_push(request: Request) -> ApiEnvelope:
    """接诊推送接收（HIS→我方）：验签 + 校验载荷 + ACK。

    注：本期仅建立签名通道并校验载荷；患者/接诊的建立仍由 /embed/start 负责
    （接诊推送与 embed/start 的联动属待定设计）。
    """
    body_raw = (await request.body()).decode("utf-8")
    app_id = request.headers.get("X-App-Id", "")
    timestamp = request.headers.get("X-Timestamp", "")
    nonce = request.headers.get("X-Nonce", "")
    sign = request.headers.get("X-Sign", "")

    if not timestamp_fresh(timestamp, settings.his_sign_clock_skew_seconds):
        return err(40002, "时间戳过期或非法")
    if not app_id or app_id != settings.his_inbound_app_id:
        return err(40003, "appId 无效")
    if not verify_sign(app_id, timestamp, nonce, body_raw, sign, settings.his_inbound_app_secret):
        return err(40001, "签名校验失败")
    try:
        payload = AdmitPushRequest.model_validate_json(body_raw)
    except ValidationError:
        return err(40004, "参数缺失或格式错误")

    # 本期：仅确认收到（回声 visit_id）。后续按设计补患者/接诊联动。
    return ok({"visit_id": payload.visit_id})
```

- [ ] **Step 4: 注册路由**

修改 `backend/app/api/v1/__init__.py`：
1. 在 `from app.api.v1 import (...)` 的导入列表里加入 `his`（与 `embed, desktop` 并列）。
2. 在文件末尾 `router.include_router(desktop.router, ...)` 之后加入：

```python
router.include_router(his.router, tags=["HIS对接"])
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_admit.py -v`
Expected: 4 passed

- [ ] **Step 6: 跑全部 HIS 测试确认无回归**

Run: `cd backend && venv/Scripts/python.exe -m pytest tests/test_his_signing.py tests/test_his_writeback_builder.py tests/test_his_admit.py tests/test_his_adapter.py -v`
Expected: 全部 passed

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/his.py backend/app/api/v1/__init__.py backend/tests/test_his_admit.py
git commit -m "feat(his): 接诊推送接收接口（HMAC验签+ACK），受保险丝保护"
```

---

## 自检（写完计划后对照 spec）

**1. spec 覆盖：** 范围里 4 项「我方自己说了算」——签名（Task 2）、统一信封（Task 3）、接诊接收（Task 5）、回写 payload 组装（Task 4），配置占位（Task 1）✅。DB 不动：均未改表，仅读现有 Encounter/InquiryInput/RecordVersion ✅。回写发送/接诊联动/住院字段已在开头明确排除 ✅。

**2. 占位扫描：** 无 TBD/TODO；每个代码步骤都给了完整代码与可运行命令 ✅。

**3. 类型一致性：** `compute_sign/verify_sign/timestamp_fresh` 三处签名在 signing.py、his.py、两个测试文件中一致；`ApiEnvelope/ok/err` 一致；`build_writeback_payload(db, encounter_id, app_version)` 与测试一致；`AdmitPushRequest` 字段在 models.py 与 his.py 一致 ✅。

**4. 待人工核对的外部假设（实现时第一步先确认，避免照错）：**
- `backend/app/his_adapter/models.py` 顶部是否已 import `Field / Optional / Literal`，缺则补。
- `backend/app/api/v1/__init__.py` 导入列表与 include_router 段的确切写法（按现有 embed/desktop 风格照抄）。
- `InquiryInput` 字段名以 `backend/app/models/encounter.py` 实际为准（计划用的是已核对过的真实名）。

---

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-06-18-his-medical-record-integration.md`. 两种执行方式：

**1. 子代理驱动（推荐）** — 每个 Task 派新子代理实现、Task 间审查、快速迭代。

**2. 当前会话内执行** — 在本会话按 executing-plans 批量执行、设检查点审查。

**选哪种？**

