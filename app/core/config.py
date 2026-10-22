from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _with_driver(url: str, driver: str) -> str:
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return driver + "://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # Database
    DATABASE_URL: str
    SECRET_KEY: str

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_TIMEOUT_SECONDS: float = 30.0

    # App
    APP_NAME: str = "CareerLine API"
    APP_ENV: str = "development"
    APP_PORT: int = 8000
    API_PREFIX: str = "/api/v1"  # Global prefix for every API route (health checks sit outside it)

    # Logging: JSON lines in production, readable console output in development
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # Comma-separated list of frontend origins allowed to call the API
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Refuse to start when the database is behind the latest migration
    CHECK_MIGRATIONS_ON_STARTUP: bool = True

    # Sample API (app/sample): typed sample answers for the endpoints that are not built yet, so
    # the frontend can build against the real contract. Unset = on everywhere except production.
    SAMPLE_API_ENABLED: bool | None = None
    # Where the sample flows (checkout, invitations) keep their state. A file, so every server
    # worker on one machine sees the same state; it is reset when the machine restarts.
    SAMPLE_STATE_FILE: str = "/tmp/careerline-sample-state.json"

    # Assessment config
    PASS_THRESHOLD: int = 60
    WEAK_THRESHOLD: int = 60
    QUESTIONS_PER_LEVEL: int = 25

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def sample_api_enabled(self) -> bool:
        if self.SAMPLE_API_ENABLED is not None:
            return self.SAMPLE_API_ENABLED
        return not self.is_production

    @property
    def async_database_url(self) -> str:
        return _with_driver(self.DATABASE_URL, "postgresql+asyncpg")

    @property
    def sync_database_url(self) -> str:
        return _with_driver(self.DATABASE_URL, "postgresql")


settings = Settings()  # required values (DATABASE_URL, SECRET_KEY) come from the environment
