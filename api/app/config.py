from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Defaults to production so a missing ENV can never switch on dev behaviour.
    env: Literal["dev", "test", "staging", "production"] = "production"

    database_url: str
    redis_url: str
    cors_origins: list[str] = ["http://localhost:5173"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    app_tz: str = "Asia/Bangkok"
    trusted_proxy_ips: list[str] = ["127.0.0.1"]

    db_pool_size: int = 20
    db_max_overflow: int = 10

    llm_base_url: str = "https://api.openai.com/v1"
    # Path to a file holding the provider API key — mounted from the secret
    # store, one per environment. Read on every call so a rotated key takes
    # effect without a restart; the key itself is never held in settings.
    # Required outside dev/test (startup refuses to boot without it).
    llm_api_key_file: str | None = None
    # Used only when the main application's quota:{user_id} has no `limit`.
    llm_token_quota: int = 1_000_000

    # The account app/jobs/quota_health.py inspects to catch the main
    # application changing the shape of quota:{user_id}.
    quota_health_user_id: int | None = None

    # Dev only: act as this user without a main-application session. Startup
    # refuses to boot if it is set while ENV is anything but "dev".
    dev_session_user_id: int | None = None
    dev_session_role: Literal["user", "admin"] = "user"


settings = Settings()
