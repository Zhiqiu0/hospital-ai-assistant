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
import ipaddress
from typing import Optional

from fastapi import Request


# audit_logs.ip_address 是 VARCHAR(50)，PostgreSQL 对超长值抛 22001 而不是截断，
# 而 log_action 的写入失败是被 except 静默吞掉的——两者一叠加，攻击者只要发一个
# 超长 X-Forwarded-File 头，本次请求的审计就整条丢失且业务照常 200。
# 放开归属校验后审计是唯一追责手段，等于给了个一键关闭开关。
# 这里统一做净化：限长 + 限字符集（IPv4/IPv6 只可能是十六进制、点、冒号、百分号）。
_IP_MAX_LEN = 45          # IPv6 最长 45 字符，留在列宽 50 之内


def _sanitize_ip(value: Optional[str]) -> Optional[str]:
    """净化来源 IP：必须是合法 IPv4/IPv6，否则一律丢弃返回 None。

    用 ipaddress 真校验而不是只限字符集——后者会放行 45 个 'A'（A-F 是合法
    十六进制字符），那种垃圾值存进审计比留空更糟：它是可伪造的错误信息，
    追责时会把人指向不存在的机器。宁可留空，也不记一个假的。
    """
    if not value:
        return None
    v = value.strip()
    if not v or len(v) > _IP_MAX_LEN:
        return None
    # IPv6 可能带 zone id（fe80::1%eth0），ipaddress 不认，去掉再校验
    candidate = v.split("%", 1)[0]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return v


def get_client_ip(request: Request) -> Optional[str]:
    """从请求中提取真实客户端 IP，按 XFF → X-Real-IP → socket 兜底顺序读取。

    - 反代环境（生产）：拿到客户端真实公网 IP，审计/限速生效
    - 值一律净化（限长 45 + 限字符集），防止超长/脏值把审计写入撑爆
    - 直连环境（本地开发）：兜底走 request.client.host，行为不变
    """
    # X-Real-IP 优先（2026-08-13 第四轮审计修复）：生产 nginx 用 $remote_addr 设置它，
    # 客户端伪造不了；而 XFF 用的是 $proxy_add_x_forwarded_for（追加语义），
    # **客户端送来的值原样保留在最左段**，谁都能把审计里的来源 IP 写成任意值。
    # 原先 XFF 排在前面，等于优先采信可伪造的那个。
    real_ip = _sanitize_ip(request.headers.get("x-real-ip"))
    if real_ip:
        return real_ip

    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = _sanitize_ip(xff.split(",")[0])
        if first:
            return first

    if request.client:
        return _sanitize_ip(request.client.host)

    return None


def get_client_ip_from_scope(scope) -> Optional[str]:
    """同 get_client_ip，但直接吃 ASGI scope。

    中间件层拿不到 FastAPI 的 Request 对象（那是路由层才构造的），而来源 IP
    要在请求最开始就写进上下文供审计使用，故提供这个 scope 版本。
    解析顺序与 get_client_ip 完全一致：X-Real-IP → XFF → socket 兜底，并做同样的净化。
    """
    headers = {}
    for name, value in scope.get("headers", []) or []:
        key = name.decode("latin-1", errors="replace").lower()
        if key in ("x-forwarded-for", "x-real-ip") and key not in headers:
            headers[key] = value.decode("latin-1", errors="replace")

    # 顺序与净化规则同 get_client_ip：可信的 X-Real-IP 优先于可伪造的 XFF
    real_ip = _sanitize_ip(headers.get("x-real-ip"))
    if real_ip:
        return real_ip

    xff = headers.get("x-forwarded-for")
    if xff:
        first = _sanitize_ip(xff.split(",")[0])
        if first:
            return first

    client = scope.get("client")
    if client:
        return _sanitize_ip(client[0])

    return None
