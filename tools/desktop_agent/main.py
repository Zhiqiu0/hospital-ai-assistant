"""MediScribe 桌面 Agent 入口（main.py）

启动顺序:
  1. 加载配置(jinsuanpan_map.yaml)
  2. 启动 FastAPI HTTP Server(127.0.0.1:7788)
  3. 注册全局快捷键 Ctrl+Alt+M
  4. 启动系统托盘(让用户能看到 Agent 在运行)

主线程跑系统托盘,HTTP Server 跑在后台线程,快捷键监听跑在第三个线程。

骨架版:HTTP Server 实现 /ping;HIS 操作部分留接口待 his/ 子模块实现。
"""

import logging
import os
import threading
from pathlib import Path

import uiautomation as auto
import uvicorn

from http_server import app, set_agent_context

# 默认监听端口(被占用时尝试 7789-7792)
DEFAULT_PORT = 7788
PORT_RANGE = [7788, 7789, 7790, 7791, 7792]

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mediscribe.agent")


def find_available_port() -> int:
    """端口被占用时按 PORT_RANGE 顺序找下一个。"""
    import socket

    for port in PORT_RANGE:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
            sock.close()
            return port
        except OSError:
            continue
    raise RuntimeError(f"端口范围 {PORT_RANGE} 全部被占用,Agent 无法启动")


def run_http_server(port: int) -> None:
    """后台线程跑 FastAPI HTTP Server(仅在 NON-reload 模式下被子线程调用)。

    生产模式(打包 exe)主线程跑托盘 + 快捷键,HTTP Server 跑在子线程。
    """
    logger.info("HTTP Server 启动于 127.0.0.1:%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


def main() -> None:
    logger.info("MediScribe 桌面 Agent 启动中...")

    # 1. 找可用端口
    port = find_available_port()

    # 2. 设置 Agent 上下文(供 http_server 路由访问)
    set_agent_context(
        {
            "port": port,
            "version": "0.1.0-mvp",
            "config_dir": Path(__file__).parent / "his",
        }
    )

    # 3. 启动 HTTP Server
    # 开发模式 (MEDISCRIBE_AGENT_RELOAD=1) 直接在主线程跑 uvicorn reload:
    #   - uvicorn reload 要在主线程注册 SIGINT/SIGTERM 信号,放子线程会报
    #     "signal only works in main thread"
    #   - 反正骨架版主线程也没事干(托盘 / 快捷键还没接),让给 uvicorn
    # 生产模式跑 daemon 子线程,把主线程让给托盘 / 快捷键监听
    reload = os.environ.get("MEDISCRIBE_AGENT_RELOAD") == "1"

    if reload:
        logger.info("HTTP Server (reload) 主线程启动于 127.0.0.1:%d", port)
        uvicorn.run(
            "http_server:app",
            host="127.0.0.1",
            port=port,
            log_level="info",
            reload=True,
            reload_dirs=[str(Path(__file__).parent)],
        )
        return  # uvicorn 自己处理 Ctrl+C 退出

    # 生产路径
    server_thread = threading.Thread(
        target=run_http_server, args=(port,), daemon=True, name="agent-http-server"
    )
    server_thread.start()

    # 4. 初始化 UI Automation(只一次,避免重复 COM init 卡死)
    # uiautomation 2.0.20 在多线程下要显式调
    auto.uiautomation.InitializeUIAutomationInCurrentThread()

    # 5. TODO: 启动托盘 / 快捷键监听(MVP 后续)
    logger.info("骨架版:暂未启动托盘,按 Ctrl+C 退出")
    try:
        server_thread.join()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C,Agent 退出")


if __name__ == "__main__":
    main()
