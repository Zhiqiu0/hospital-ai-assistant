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
| 前端 | React 19 + Ant Design 5 + TypeScript |
| 后端 | Python 3.11 + FastAPI |
| 数据库 | PostgreSQL 16 |
| 缓存 | Redis 7（PACS 缩略图缓存 + HIS 联动跨进程事件总线，多 worker 部署下核心依赖） |
| AI模型 | DeepSeek + 阿里云通义（语音/影像） |
| 容器 | docker compose（PostgreSQL / Redis / Orthanc / 前后端），见 docker-compose.yml |

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
│   │   │   ├── qc_engine/  # 病历质控评分引擎（浙江省标准 rubric）
│   │   │   └── rule_engine/# 医保风险规则
│   │   ├── his_adapter/    # HIS 对接（接诊推送/回写/对账）
│   │   └── core/           # 鉴权、中间件
│   ├── init_db.py          # 默认种子数据（表结构归 alembic）
│   ├── alembic_guard.py    # 迁移守卫（存量库 stamp 到基线，零 DDL）
│   └── requirements.txt
├── frontend/               # React 前端
│   └── src/
│       ├── pages/          # 页面
│       ├── components/     # 组件
│       ├── hooks/          # 业务 hooks
│       ├── domain/         # 领域类型
│       ├── services/       # API调用
│       └── store/          # 状态管理（zustand 子 store）
└── docs/                   # 评审/对接材料
```

## 快速启动

```bash
# 1. 确保 PostgreSQL 已启动
# 可选：如你已通过 Docker 启动数据库/Redis，保持容器运行即可

# 2. 启动后端
cd backend
pip install -r requirements.txt
python alembic_guard.py          # 迁移守卫（老库打标记，零 DDL）
python -m alembic upgrade head   # 建表/改表（唯一 schema 通道）
python init_db.py                # 播种子（admin/doctor01/科室/模板）
uvicorn app.main:app --reload --port 8010

# 3. 启动前端
cd frontend
npm install
npm run dev
```

## 访问地址

- 前端：http://localhost:5174
- 后端API：http://localhost:8010
- API文档：http://localhost:8010/docs

## 当前状态说明

- 仓库已内置 `docker-compose.yml`、`backend/Dockerfile`、`backend/alembic/` 迁移目录
- 生产走 docker compose（前端 + 后端 + PostgreSQL + Redis + Orthanc + uptime-kuma）
- 数据库变更走 `alembic` 单通道（2026-08-12 收口；禁止直接 SQL 改 schema）：
  改 model 后写一条**幂等** revision（inspector 判断已存在再加，基线是 create_all
  语义，非幂等迁移会在全新库上撞车），CI 的空库门禁会拦截违规迁移
- Redis 已是核心依赖：PACS 缩略图缓存 + HIS 联动的跨 worker 事件总线（多 worker 部署必需）

## 环境变量

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
```

## 默认测试账号

- 管理员：`admin / admin123456`
- 医生：`doctor01 / doctor123`
