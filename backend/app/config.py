from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    secret_key: str
    access_token_expire_minutes: int = 1440

    # AI 模型 - DeepSeek（病历生成、质控）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # AI 模型 - 阿里云通义千问（PACS 图像分析）
    aliyun_api_key: str = ""
    aliyun_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    aliyun_model: str = "qwen-vl-plus"

    # 阿里云 AccessKey（余额查询）
    alibaba_access_key_id: str = ""
    alibaba_access_key_secret: str = ""

    # 应用
    app_env: str = "development"
    app_debug: bool = True
    app_port: int = 8000
    allowed_origins: str = "http://localhost:5174,http://localhost:5173,http://localhost:3000"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ("../.env", ".env")
        case_sensitive = False


settings = Settings()
