from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库
    database_url: str

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    secret_key: str
    access_token_expire_minutes: int = 1440

    # AI 模型
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 应用
    app_env: str = "development"
    app_debug: bool = True
    app_port: int = 8000
    allowed_origins: str = "http://localhost:5174,http://localhost:5173,http://localhost:3000"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = "../.env"
        case_sensitive = False


settings = Settings()
