"""
应用配置（config.py）

使用 pydantic-settings 从环境变量 / .env 文件加载配置。
所有敏感信息（密钥、API Key）均应通过环境变量注入，不应硬编码。

配置来源优先级（从高到低）：
  1. 系统环境变量
  2. 项目根目录 .env 文件
  3. 上级目录 ../.env 文件
  4. 字段默认值

使用方式：
  from app.config import settings
  print(settings.database_url)
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """全局配置类，所有字段对应同名（不区分大小写）的环境变量。"""

    # ── 数据库 ────────────────────────────────────────────────────────────────
    # PostgreSQL 连接串，格式：postgresql://user:password@host:port/dbname
    # database.py 会自动转换为 asyncpg 驱动格式
    database_url: str

    # ── JWT 认证 ──────────────────────────────────────────────────────────────
    # 签名密钥，生产环境必须设置为随机长字符串（至少 32 位）
    secret_key: str
    # 访问令牌有效期（分钟），默认 1440 分钟 = 24 小时
    access_token_expire_minutes: int = 1440

    # ── AI 模型：DeepSeek（病历生成、质控、润色等核心功能）────────────────────
    deepseek_api_key: str = ""                              # DeepSeek API Key
    deepseek_base_url: str = "https://api.deepseek.com"    # API 基础 URL
    deepseek_model: str = "deepseek-chat"                  # 默认模型名

    # ── AI 模型：阿里云通义千问（PACS 图像分析、语音转写兜底）────────────────
    aliyun_api_key: str = ""                                            # 阿里云灵积 API Key
    aliyun_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    aliyun_model: str = "qwen-vl-plus"                                  # 视觉模型（PACS 分析）

    # ── 阿里云 AccessKey（余额/用量查询，非 API 调用）────────────────────────
    alibaba_access_key_id: str = ""
    alibaba_access_key_secret: str = ""

    # ── Orthanc DICOM 服务器（R1 迁移：替代 pacs.py 本地 DICOM 处理）─────────
    # 本地开发：docker compose up -d orthanc 起来后默认地址 http://localhost:8042
    # 生产部署：服务发现走 docker compose 的服务名 http://orthanc:8042
    orthanc_base_url: str = "http://localhost:8042"
    orthanc_username: str = "mediscribe"
    orthanc_password: str = "mediscribe-orthanc-2026"

    # ── 7-Zip 可执行文件路径（解压 RAR/7Z/TAR.GZ/ISO 等格式用）──────────────
    # 留空时：自动搜 PATH + 常见安装位置；找不到则解压非 ZIP 格式时报错
    # 用户自定义路径示例：SEVENZIP_PATH=C:\APP\ToolApp\7-Zip\7z.exe
    # Linux 服务器一般装 p7zip-full 后 7z 在 PATH 里，无需配置
    sevenzip_path: str = ""

    # ── Redis 缓存（PACS 缩略图 + 后续通用缓存层）──────────────────────────
    # 本地开发：用本机 Redis（默认 redis://localhost:6379/0）
    # 生产 Docker：docker compose 起 redis 服务，URL 走 redis://redis:6379/0
    # 留空时缓存自动降级（直接走 Orthanc，性能差但功能正常）
    redis_url: str = "redis://localhost:6379/0"
    # 缩略图缓存 TTL（秒）：默认 7 天。短期内 study 会被反复查看
    thumbnail_cache_ttl: int = 7 * 24 * 3600

    # ── 应用运行环境 ──────────────────────────────────────────────────────────
    app_env: str = "development"             # "development" / "production"
    app_debug: bool = True                   # True 时 SQLAlchemy 打印 SQL 语句
    # 允许跨域访问的前端域名，多个域名用逗号分隔
    # 示例："http://localhost:5174,https://mediscribe.cn"
    allowed_origins: str = "http://localhost:5174"

    # ── 日志 ──────────────────────────────────────────────────────────────────
    # 根 logger 最低级别，main.py 启动时传给 setup_logging
    log_level: str = "INFO"

    # ── Sentry 错误监控 ────────────────────────────────────────────────────────
    # DSN 留空时完全跳过 Sentry 初始化（本地开发默认不上报，避免污染生产项目）
    # 形如：https://xxx@xxx.ingest.sentry.io/yyy
    sentry_dsn: str = ""
    # 部署环境标识，Sentry 据此分流告警（dev/staging/prod 各看各的）
    # 默认沿用 app_env，可在 .env 单独覆盖
    sentry_environment: str = ""
    # 性能 trace 采样率：0=完全关闭，0.05=5% 采样
    # 开发环境置 0（避免吃 Free 额度），生产环境建议 0.05
    sentry_traces_sample_rate: float = 0.0
    # release 标识：CI deploy 时注入 git short SHA（如 "a7873b2"），让 Sentry 能
    # 把 event 关联到具体 commit，启用 Suspect Commits / 部署历史等功能
    # 本地开发不需要传，留空表示不带 release tag
    sentry_release: str = ""

    @property
    def origins_list(self) -> list[str]:
        """将逗号分隔的 allowed_origins 字符串转换为列表，供 CORS 中间件使用。"""
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        # 按顺序尝试加载 .env 文件（支持 Docker 挂载和本地开发两种路径）
        env_file = ("../.env", ".env")
        case_sensitive = False  # 环境变量名不区分大小写


# 模块级单例，全局使用 `from app.config import settings`
settings = Settings()
