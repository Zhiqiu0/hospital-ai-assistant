# -*- coding: utf-8 -*-
"""前后端 API 契约门禁（scripts/check_api_contract.py）

2026-08-12 体检清理项「前后端 OpenAPI 契约」落地（简单优先版）：
不做全量类型生成改造，先解决最疼的一类事故——**前端调用了后端不存在的
端点**（404 被兜底逻辑静默吞掉，功能悄悄失效；复检刚抓到过一例：
fetchLatestRecord 用 GET 调了只存在 POST 的集合路径）。

做法：
  1. 从 FastAPI 应用导出真实 OpenAPI（方法+路径）清单
  2. 静态扫描 frontend/src 里全部 api.get/post/... 与 fetch('/api/v1...')
     调用（axios 方法取自调用名；fetch 看其后 options 里的 method，缺省 GET）
  3. 归一化（模板插值 ${...} → {p}，去 query）后按**方法级**比对，
     任何一条对不上 spec → 红灯退出

在 CI 后端 job 里跑（backend 为工作目录）：python ../scripts/check_api_contract.py
本地：backend/venv/Scripts/python ../scripts/check_api_contract.py
"""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
FRONTEND_SRC = REPO / "frontend" / "src"

# 不在 OpenAPI spec 里的合法调用（WebSocket / 非 HTTP 语义），逐条注明原因
ALLOWLIST = {
    ("GET", "/api/v1/ai/voice-stream"),  # WebSocket（语音实时转写），不产出到 openapi
    ("GET", "/api/v1/his/ws"),           # WebSocket（HIS 长连接通道）
}


def load_spec() -> list[tuple[str, list[str]]]:
    """导出后端 OpenAPI 全部 (方法, 路径段列表)。"""
    # Settings 必填项兜底（与 CI 测试同款假值），导 app 不需要真实凭证/数据库
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("SECRET_KEY", "contract-check-not-for-production")
    os.environ.setdefault("ORTHANC_PASSWORD", "contract-check-not-for-production")
    sys.path.insert(0, str(BACKEND))
    from app.main import app  # noqa: E402

    out: list[tuple[str, list[str]]] = []
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method in ("get", "post", "put", "patch", "delete"):
                out.append((method.upper(), path.strip("/").split("/")))
    return out


# api.<method>('path' / `path`)：axios 封装，baseURL=/api/v1
_AXIOS_RE = re.compile(r"""api\.(get|post|put|patch|delete)\(\s*([`'"])([^`'"]+)\2""")
# fetch('/api/v1/...')：绕过 axios 的裸调用（SSE/流式下载等）
_FETCH_RE = re.compile(r"""fetch\(\s*([`'"])(/api/v1[^`'"]+)\1""")
# fetch options 里的 method（在 fetch( 之后 ~300 字符内找）
_METHOD_RE = re.compile(r"""method:\s*['"](\w+)['"]""")


def _normalize(raw: str) -> str:
    path = raw.split("?")[0]                    # 去 query
    return re.sub(r"\$\{[^}]*\}", "{p}", path)  # 模板插值 → 参数段


def scan_frontend_calls() -> dict[tuple[str, str], list[str]]:
    """扫出前端全部 API 调用 → {(方法, 归一化路径): [出处文件:行号]}。"""
    calls: dict[tuple[str, str], list[str]] = {}

    def add(method: str, raw: str, f: Path, text: str, offset: int) -> None:
        lineno = text.count("\n", 0, offset) + 1
        key = (method.upper(), _normalize(raw))
        calls.setdefault(key, []).append(f"{f.relative_to(REPO)}:{lineno}")

    for f in FRONTEND_SRC.rglob("*.ts*"):
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in _AXIOS_RE.finditer(text):
            raw = m.group(3)
            raw = raw if raw.startswith("/api/") else f"/api/v1{raw}"  # 补 baseURL
            add(m.group(1), raw, f, text, m.start())
        for m in _FETCH_RE.finditer(text):
            # fetch 的 method 在其后的 options 里（多行），缺省 GET
            tail = text[m.end(): m.end() + 300]
            mm = _METHOD_RE.search(tail)
            add(mm.group(1) if mm else "GET", m.group(2), f, text, m.start())
    return calls


def matches(call_segs: list[str], spec_segs: list[str]) -> bool:
    """段数相同且逐段相等（任一侧是参数段视为通配）。"""
    if len(call_segs) != len(spec_segs):
        return False
    for c, s in zip(call_segs, spec_segs):
        if c != s and not s.startswith("{") and c != "{p}":
            return False
    return True


def main() -> int:
    spec = load_spec()
    calls = scan_frontend_calls()
    bad: list[str] = []
    for (method, path), wheres in sorted(calls.items()):
        if (method, path) in ALLOWLIST:
            continue
        segs = path.strip("/").split("/")
        if not any(m == method and matches(segs, s) for m, s in spec):
            bad.append(f"  {method} {path}\n    调用处: " + "; ".join(wheres[:3]))
    print(f"[contract] 后端 spec {len(spec)} 条(方法级)，前端调用 {len(calls)} 条")
    if bad:
        print("[contract] ❌ 前端调用与后端真实端点对不上（方法+路径）：")
        print("\n".join(bad))
        return 1
    print("[contract] ✅ 全部前端调用都能命中后端真实端点")
    return 0


if __name__ == "__main__":
    sys.exit(main())
