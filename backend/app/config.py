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
    # 访问令牌有效期（分钟），默认 43200 分钟 = 30 天
    # （2026-08-11 从 24h 放宽：诊室固定电脑场景，医生不该频繁重登；
    #   保密级别经用户评估可接受，登出仍走 jti 黑名单即时失效）
    access_token_expire_minutes: int = 43200

    # bcrypt 强度（2026-08-13 压测定档）：生产是 2 核机，bcrypt 是纯 CPU 且并行度
    # 上限就是核数。实测 rounds=12 时 24 人同时登录中位 2.3s、最慢 3.7s，且期间
    # 其他接口 p95 从 14ms 劣化到 463ms——早高峰全院同时上线会拖垮整机。
    # rounds=10 是 OWASP 密码存储指南的推荐下限，单次约 1/4 耗时；配合登录限流
    # （同用户名 10次/10分钟，在线爆破本就走不通），这个取舍是划算的。
    bcrypt_rounds: int = 10

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
    # ORTHANC_PASSWORD 必须由 .env 显式注入——没有默认值，启动时 Pydantic 会报错。
    # 之前的硬编码默认值 "mediscribe-orthanc-2026" 跟 GitHub 公网仓库可见，
    # 任何忘了设环境变量的部署都会用这个公网密码连 Orthanc，导致 PHI 泄露风险。
    orthanc_password: str

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
    # 注：原 app_debug（控制 SQL 打印）已废弃删除——SQL 打印改由 DB_ECHO 环境变量
    # 控制（见 database.py），app_debug 全仓零读取。compose 里残留的 APP_DEBUG 环境
    # 变量会被 pydantic 忽略（未设 extra=forbid），无副作用。
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

    # ── HIS 对接（金算盘等院内 HIS 接口模式）──────────────────────────────────
    # 全局保险丝：false 时所有 HIS 对接路由（/his/* 推送、回写、WS、叫号）直接 503，
    # 完全不影响现有 SaaS（mediscribe.cn 普通医生登录使用）。
    # 任何对接 bug 都可以通过把这个改回 false + 重启后端 5 秒内全院切回纯 SaaS。
    # （旧 /embed/* 桌面 Agent 入口已于 2026-08-12 整体下线删除。）
    his_adapter_enabled: bool = False
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
    his_writeback_max_retries: int = 2    # 写入/刷新失败（网络异常或 5xx）重试次数

    @property
    def origins_list(self) -> list[str]:
        """将逗号分隔的 allowed_origins 字符串转换为列表，供 CORS 中间件使用。"""
        return [o.strip() for o in self.allowed_origins.split(",")]

    def validate_runtime(self) -> None:
        """启动期一致性校验（2026-08-11 病历安全）：防"半配置"状态静默上线。

        HIS 保险丝开着(his_adapter_enabled=True)但入站验签凭证没配全时，接诊推送会
        因验签失败被全部拒收、病历回写通道也无从建立——这类"开关开了但没凭证"的半
        配置，过去要等真网冒烟才发现。

        生产环境(app_env=production)一律 fail-fast（把问题挡在部署阶段）；
        开发/测试环境只告警不阻断（本地常把开关打开做联调彩排，凭证可后配）。
        """
        if not self.his_adapter_enabled:
            return
        missing = [
            name for name, val in (
                ("HIS_INBOUND_APP_ID", self.his_inbound_app_id),
                ("HIS_INBOUND_APP_SECRET", self.his_inbound_app_secret),
            )
            if not (val or "").strip()
        ]
        if not missing:
            return
        msg = (
            f"HIS_ADAPTER_ENABLED=true 但缺少入站验签凭证：{', '.join(missing)}。"
            "请补齐凭证或把保险丝关回 false。"
        )
        if self.app_env == "production":
            raise ValueError(msg)
        import logging
        logging.getLogger(__name__).warning("config.validate: %s（非生产环境仅告警）", msg)

    class Config:
        # 按顺序尝试加载 .env 文件（支持 Docker 挂载和本地开发两种路径）
        env_file = ("../.env", ".env")
        case_sensitive = False  # 环境变量名不区分大小写


# 模块级单例，全局使用 `from app.config import settings`
settings = Settings()
# 启动期一致性校验（配置错误即 fail-fast，挡在部署阶段而非等真网冒烟发现）
settings.validate_runtime()
