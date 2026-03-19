# MedAssist 临床接诊智能助手系统

> 一期 MVP | 面向医生端 Web 的 AI 临床辅助平台

## 项目简介

帮助医生在接诊过程中：
- **问诊更全面** — AI智能追问建议，减少关键信息遗漏
- **病历更高效** — 一键生成标准化病历草稿，支持续写/润色/补全
- **质控更规范** — 自动扫描完整性、规范性、医保风险问题

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 18 + Ant Design 5 + TypeScript |
| 后端 | Python 3.13 + FastAPI |
| 数据库 | PostgreSQL 16 |
| 缓存 | Redis 7（当前版本仅保留配置，核心流程未强依赖） |
| AI模型 | DeepSeek API |
| 容器 | 可选：外部 Docker 启动 PostgreSQL / Redis |

## 项目结构

```
medassist/
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/         # 接口路由
│   │   ├── models/         # 数据库模型
│   │   ├── schemas/        # 请求/响应结构
│   │   ├── services/       # 业务逻辑
│   │   │   ├── ai/         # AI调用服务
│   │   │   └── rule_engine/# 规则引擎
│   │   └── core/           # 鉴权、中间件
│   ├── init_db.py          # 初始化数据库与默认数据
│   └── requirements.txt
├── frontend/               # React 前端
│   └── src/
│       ├── pages/          # 页面
│       ├── components/     # 组件
│       ├── services/       # API调用
│       └── store/          # 状态管理
├── docs/                   # 文档
│   ├── database_design.md  # 数据库设计
│   └── api_definition.md   # 接口定义
├── 启动指南.md             # 本地启动说明
└── test_api.py             # 简单联调脚本
```

## 快速启动

```bash
# 1. 确保 PostgreSQL 已启动
# 可选：如你已通过 Docker 启动数据库/Redis，保持容器运行即可

# 2. 启动后端
cd backend
pip install -r requirements.txt
python init_db.py
uvicorn app.main:app --reload --port 8000

# 3. 启动前端
cd frontend
npm install
npm run dev
```

## 访问地址

- 前端：http://localhost:5174
- 后端API：http://localhost:8000
- API文档：http://localhost:8000/docs

## 当前状态说明

- 仓库当前未内置 `docker-compose.yml`、`Dockerfile`、`alembic/` 迁移目录
- 如果你本地已通过 Docker 启动 PostgreSQL / Redis，可以直接复用现有容器
- Redis 配置已预留，但当前 MVP 主流程主要依赖 PostgreSQL 与 DeepSeek API

## 环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
```

## 默认测试账号

- 管理员：`admin / admin123456`
- 医生：`doctor01 / doctor123`
