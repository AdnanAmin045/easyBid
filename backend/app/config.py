from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    """Process configuration, read from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase Postgres connection string (session pooler)
    database_url: str = ""
    redis_url: str = ""
    # The polling loop runs inside the web process. With false, the arq worker runs it and the web process
    # only takes over if the worker stops reporting in.
    embedded_scheduler: bool = True

    freelancer_token: str = ""
    freelancer_base_url: str = "https://www.freelancer.com/api"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    admin_email: str = ""
    admin_password: str = ""
    secret_key: str = ""
    token_ttl_hours: int = 720  # stay signed in for 30 days
    cors_origins: str = "http://localhost:3000"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    def missing_required(self) -> list[str]:
        required = ("database_url", "freelancer_token", "admin_email", "admin_password", "secret_key")
        return [name.upper() for name in required if not getattr(self, name)]


@lru_cache
def get_env() -> Env:
    return Env()
