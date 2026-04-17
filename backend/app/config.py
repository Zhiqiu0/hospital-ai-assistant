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

    # ── 应用运行环境 ──────────────────────────────────────────────────────────
    app_env: str = "development"             # "development" / "production"
    app_debug: bool = True                   # True 时 SQLAlchemy 打印 SQL 语句
    # 允许跨域访问的前端域名，多个域名用逗号分隔
    # 示例："http://localhost:5174,https://mediscribe.cn"
    allowed_origins: str = "http://localhost:5174"

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
