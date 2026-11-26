from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _with_driver(url: str, driver: str) -> str:
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return driver + "://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    """What differs between machines and servers. Fixed rules (test length, sign-in limits,
    grace periods ...) are constants in the module that uses them."""

    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # Database
    DATABASE_URL: str
    SECRET_KEY: str

    # App
    APP_ENV: str = "development"
    # The port python -m app serves on (and scripts/start.sh)
    PORT: int = Field(default=8000, ge=1, le=65535)

    # Logging: JSON lines in production, readable console output in development
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    # Errors go to Sentry when set (the project's DSN); required in production
    SENTRY_DSN: str = ""

    # Comma-separated list of frontend origins allowed to call the API
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    # The website's address: invitation links and where Paystack sends people back point to it
    FRONTEND_URL: str = "http://localhost:5173"
    # The sign-in cookie's SameSite. lax (production): the site and the API share a domain, so
    # the site's requests carry the cookie and other sites' requests do not. none: the test
    # server, whose site and API are on different domains (Safari and private windows still
    # block it there). Either way a cookie only counts on a change from one of CORS_ORIGINS.
    SESSION_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    # Background jobs (app/jobs). Production runs `python -m app.worker` as its own service; a
    # server with no worker service sets RUN_JOBS_IN_WEB=true to run the jobs inside the API
    RUN_JOBS_IN_WEB: bool = False

    # OpenAI (optional): without a key, plain recommendations and explanations are used
    OPENAI_API_KEY: str = ""

    # Payments: Paystack. The secret key comes only from the environment (sk_test_... on the
    # test server); without it checkout and the webhook answer 503 and nothing is charged.
    PAYSTACK_SECRET_KEY: str = ""

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("SESSION_COOKIE_SAMESITE", mode="before")
    @classmethod
    def _lower_samesite(cls, value):
        return str(value).strip().lower()

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def async_database_url(self) -> str:
        return _with_driver(self.DATABASE_URL, "postgresql+asyncpg")

    @property
    def sync_database_url(self) -> str:
        return _with_driver(self.DATABASE_URL, "postgresql")


settings = Settings()  # required values (DATABASE_URL, SECRET_KEY) come from the environment
