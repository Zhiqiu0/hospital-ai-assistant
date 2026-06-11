# MediScribe 桌面 Agent

医生电脑上常驻的 Python 程序,负责把 MediScribe 嵌入到金算盘等 HIS 系统的工作流。

## 职责

1. **探测 HIS 窗口**:Windows UI Automation 找到金算盘工作站窗口
2. **读取当前患者**:从 HIS UI 读 patient_no / 姓名 / 就诊号
3. **启动浏览器嵌入页**:调云端 `/api/v1/embed/start` 拿 token → 启动 `mediscribe.cn/embed?token=...`
4. **接收前端填入指令**:本地 HTTP Server 监听 `127.0.0.1:7788`
5. **自动写回 HIS**:按 YAML 字段映射用 UI Automation 一个个填字段
6. **进度推送**:WebSocket 实时把每个字段的填入结果推给前端展示

## 架构

```
tools/desktop_agent/
├── main.py              # 入口:启动托盘 + HTTP Server + 快捷键
├── http_server.py       # FastAPI,127.0.0.1:7788 暴露 /ping /fill /progress
├── his/
│   ├── detector.py      # 找金算盘窗口
│   ├── reader.py        # 读当前患者
│   ├── writer.py        # UI Automation 填字段
│   └── jinsuanpan_map.yaml  # 字段映射(后端会下发更新版)
├── hotkey.py            # 全局快捷键 Ctrl+Alt+M
├── tray.py              # 系统托盘
├── auth.py              # token 管理
├── logger.py            # 审计日志
└── requirements.txt
```

## MVP 范围

- ✅ Windows 平台(其他平台金算盘不存在)
- ✅ 探测金算盘 1 家 HIS(jinsuanpan_map.yaml)
- ✅ Ctrl+Alt+M 全局快捷键触发
- ✅ 系统托盘
- ⏸ 自动更新(二期)
- ⏸ 悬浮按钮(二期)
- ⏸ 多 HIS 厂商(二期)

## 开发状态

这是**骨架代码**,真机调试要在装了金算盘 HIS 的医生电脑上跑。
his_inspect.py 已经扫描了金算盘的 1453 个控件,字段映射详见
后端 `backend/app/his_adapter/jinsuanpan_map.yaml`。

## 启动方式

开发期:
```bash
cd tools/desktop_agent
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

打包(MVP 后):
```bash
python build.py  # PyInstaller 打成单文件 exe
```
