"""Agent 本地 HTTP Server(http_server.py)

监听 127.0.0.1:7788,前端嵌入页通过这里跟 Agent 通信。

CORS 严格白名单:只允许 mediscribe.cn / localhost:5174。
所有写入操作(/fill)必须带 Bearer token(后端签发的 embed_token)。

骨架版:实现 /ping 和 /fill stub,真正的 UI Automation 在 his/writer.py 完成。
"""

import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger("mediscribe.agent.http")

app = FastAPI(title="MediScribe Agent", version="0.1.0-mvp")

# CORS 白名单 — 防止恶意网站调本地 Agent
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://mediscribe.cn",
        "http://localhost:5174",  # 开发期前端
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# 由 main.py 注入 — 包含 port / version / config_dir
_agent_ctx: dict[str, Any] = {}


def set_agent_context(ctx: dict[str, Any]) -> None:
    """main.py 启动时把 Agent 上下文注入 server。"""
    _agent_ctx.update(ctx)


# ─── DTO ────────────────────────────────────────────────────────────────

class PingResponse(BaseModel):
    status: str = "ok"
    version: str
    port: int
    his_detected: bool = False
    his_brand: str | None = None


class FillField(BaseModel):
    section: str  # "intake" / "record" / "diagnosis"
    field_key: str
    value: Any


class FillRequest(BaseModel):
    encounter_id: str
    fields: list[FillField]


class FillFieldResult(BaseModel):
    field_key: str
    status: str  # success / failed / skipped / fallback_clipboard
    duration_ms: int = 0
    error_message: str | None = None


class FillResult(BaseModel):
    status: str
    encounter_id: str
    total_fields: int
    succeeded: int
    failed: int
    duration_ms: int
    field_results: list[FillFieldResult]


# ─── 路由 ───────────────────────────────────────────────────────────────

@app.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    """探测 Agent 是否在线 + HIS 是否被检测到。

    前端嵌入页 mount 时调,决定 AutoFillButton 是否 disabled。
    """
    # TODO: 调 his.detector 真正探测金算盘窗口
    his_detected = _try_detect_his()
    return PingResponse(
        version=_agent_ctx.get("version", "unknown"),
        port=_agent_ctx.get("port", 7788),
        his_detected=his_detected,
        his_brand="jinsuanpan" if his_detected else None,
    )


@app.post("/fill", response_model=FillResult)
async def fill_his(req: FillRequest) -> FillResult:
    """把字段填入 HIS。

    骨架版:返回 stub 数据,真实 UI Automation 在 his/writer.py 后续实现。
    """
    # TODO: token 校验
    # TODO: 调 his.writer.fill_fields(req.fields)
    logger.info("收到 fill 请求:encounter=%s fields=%d", req.encounter_id, len(req.fields))

    start = time.time()
    field_results: list[FillFieldResult] = []
    for f in req.fields:
        # 骨架:全部模拟成功
        field_results.append(
            FillFieldResult(
                field_key=f.field_key,
                status="success",
                duration_ms=50,
            )
        )

    duration_ms = int((time.time() - start) * 1000)
    return FillResult(
        status="success",
        encounter_id=req.encounter_id,
        total_fields=len(req.fields),
        succeeded=len(req.fields),
        failed=0,
        duration_ms=duration_ms,
        field_results=field_results,
    )


@app.get("/patient/current")
async def get_current_patient() -> dict:
    """读 HIS 当前选中的患者(Ctrl+Alt+M 触发后用)。

    骨架版:返回 mock 数据,真实读取在 his/reader.py。
    """
    # TODO: 调 his.reader.read_current_patient()
    if not _try_detect_his():
        raise HTTPException(status_code=404, detail="没找到金算盘 HIS,请先打开 HIS 并选中患者")
    return {
        "patient_no": "MOCK_PATIENT_NO",
        "visit_no": "MOCK_VISIT_NO",
        "name": "(MOCK) 测试患者",
        "his_brand": "jinsuanpan",
        "hospital_code": "H33052300957",
    }


# ─── 内部辅助 ───────────────────────────────────────────────────────────


def _try_detect_his() -> bool:
    """尝试探测金算盘窗口。骨架版 stub,真实在 his/detector.py。"""
    # TODO: 调 his.detector.find_jinsuanpan_window()
    return False
