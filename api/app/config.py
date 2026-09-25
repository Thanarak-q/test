from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    cors_origins: list[str] = ["http://localhost:5173"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    app_tz: str = "Asia/Bangkok"
    trusted_proxy_ips: list[str] = ["127.0.0.1"]

    db_pool_size: int = 20
    db_max_overflow: int = 10

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_timeout_s: float = 120.0
    llm_default_user_id: int = 1
    llm_token_quota: int = 1_000_000
    llm_output_reserve: int = 1_024


settings = Settings()
