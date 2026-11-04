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

    # Optional mailbox automatically connected from the server environment.
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_secure: bool = True
    imap_host: str = "imap.hostinger.com"
    imap_port: int = 993

    # LinkedIn posting. Two developer apps, because LinkedIn only gives the Community Management API (company pages)
    # to an app that has no other product: LINKEDIN_CLIENT_ID is the app with "Share on LinkedIn" for the personal
    # profile, LINKEDIN_ORG_CLIENT_ID the one with Community Management for the company page.
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_org_client_id: str = ""
    linkedin_org_client_secret: str = ""
    # https://<backend>/api/linkedin/callback, registered in both LinkedIn apps. Blank: this server's own URL.
    linkedin_redirect_uri: str = ""
    linkedin_api_version: str = "202610"

    @property
    def linkedin_callback(self) -> str:
        if self.linkedin_redirect_uri:
            return self.linkedin_redirect_uri
        return f"{(self.render_external_url or 'http://localhost:8000').rstrip('/')}/api/linkedin/callback"

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
