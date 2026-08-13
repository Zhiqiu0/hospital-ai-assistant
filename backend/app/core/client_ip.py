"""
客户端真实 IP 提取（core/client_ip.py）

为什么单独抽出来：
  生产部署 FastAPI 在 Caddy/Nginx 反代之后，request.client.host 拿到的是
  反代容器的内网 IP（如 172.18.0.5），导致审计日志、限速、登录失败追溯全部
  失去价值——无法定位真实攻击源 / 用户网络。

正确做法：
  1. 反代必须把 X-Forwarded-For（XFF）/ X-Real-IP 头透传给后端
  2. 后端按顺序读：XFF 第一段 → X-Real-IP → request.client.host
  3. XFF 可能是 "client, proxy1, proxy2" 形式，**第一段才是真实客户端**

安全注意：
  XFF 头可被客户端伪造（任何 HTTP 客户端都能发 X-Forwarded-For 头）。
  生产部署必须保证：只信任来自可信反代（如 Caddy/Nginx）的 XFF。
  Caddy 默认不透传客户端伪造的 XFF，会用真实 socket 替换/追加，OK；
  Nginx 需要显式 `proxy_set_header X-Real-IP $remote_addr;` 才安全。
"""
from typing import Optional

from fastapi import Request


def get_client_ip(request: Request) -> Optional[str]:
    """从请求中提取真实客户端 IP，按 XFF → X-Real-IP → socket 兜底顺序读取。

    - 反代环境（生产）：拿到客户端真实公网 IP，审计/限速生效
    - 直连环境（本地开发）：兜底走 request.client.host，行为不变
    """
    # X-Forwarded-For 可能是 "client, proxy1, proxy2"；取最左侧的真实客户端
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return None


def get_client_ip_from_scope(scope) -> Optional[str]:
    """同 get_client_ip，但直接吃 ASGI scope。

    中间件层拿不到 FastAPI 的 Request 对象（那是路由层才构造的），而来源 IP
    要在请求最开始就写进上下文供审计使用，故提供这个 scope 版本。
    解析顺序与 get_client_ip 完全一致：XFF → X-Real-IP → socket 兜底。
    """
    headers = {}
    for name, value in scope.get("headers", []) or []:
        key = name.decode("latin-1", errors="replace").lower()
        if key in ("x-forwarded-for", "x-real-ip") and key not in headers:
            headers[key] = value.decode("latin-1", errors="replace")

    xff = headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first

    real_ip = headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    client = scope.get("client")
    if client:
        return client[0]

    return None
