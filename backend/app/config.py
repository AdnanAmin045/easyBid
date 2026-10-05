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
    # Set by Render on every service. Used to keep a free instance from spinning down, which would stop polling.
    render_external_url: str = ""

    freelancer_token: str = ""
    freelancer_base_url: str = "https://www.freelancer.com/api"
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    # More Gemini keys, used in order once every Gemini model on the key before is out of quota
    gemini_api_key_2: str = ""
    gemini_api_key_3: str = ""
    gemini_api_key_4: str = ""
    gemini_api_key_5: str = ""
    # Optional free-tier providers for the model fallback chain
    groq_api_key: str = ""
    cerebras_api_key: str = ""
    mistral_api_key: str = ""

    admin_email: str = ""
    admin_password: str = ""
    secret_key: str = ""
    token_ttl_hours: int = 720  # stay signed in for 30 days
    cors_origins: str = "http://localhost:3000"

    telegram_bot_token: str = ""

    # Jobs service: Gmail OAuth client from Google Cloud, and the dashboard URL to return to after connecting.
    google_client_id: str = ""
    google_client_secret: str = ""
    # https://<backend>/api/jobs/gmail/callback, exactly as registered in Google Cloud
    google_redirect_uri: str = ""
    app_url: str = ""
    telegram_chat_id: str = ""

    @property
    def dashboard_url(self) -> str:
        """Where the dashboard lives: APP_URL, or else the first CORS origin."""
        return (self.app_url or next(iter(self.cors_origin_list), "")).rstrip("/")

    @property
    def gemini_api_keys(self) -> list[str]:
        """GEMINI_API_KEY, then GEMINI_API_KEY_2 to _5, without blanks or repeats."""
        keys = (self.gemini_api_key, self.gemini_api_key_2, self.gemini_api_key_3, self.gemini_api_key_4, self.gemini_api_key_5)
        return list(dict.fromkeys(k.strip() for k in keys if k.strip()))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    def missing_required(self) -> list[str]:
        required = ("database_url", "freelancer_token", "admin_email", "admin_password", "secret_key")
        return [name.upper() for name in required if not getattr(self, name)]


@lru_cache
def get_env() -> Env:
    return Env()
