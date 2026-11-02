from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _with_driver(url: str, driver: str) -> str:
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return driver + "://" + url[len(prefix) :]
    return url


EMAIL_BACKENDS = ("smtp", "test_mailbox", "console")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    # Database
    DATABASE_URL: str
    SECRET_KEY: str

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_TIMEOUT_SECONDS: float = 30.0
    # Day 11: the model that explains test answers (asked once per question, then kept)
    OPENAI_EXPLANATION_MODEL: str = "gpt-4o-mini"

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

    # Background jobs (app/jobs). Production runs `python -m app.worker` as its own service; the
    # free test server has no worker service, so RUN_JOBS_IN_WEB=true runs the jobs inside the API
    RUN_JOBS_IN_WEB: bool = False
    JOB_POLL_SECONDS: float = 2.0  # how often an idle worker looks for new jobs
    JOB_LEASE_SECONDS: float = 300.0  # a job is retried if its worker is silent this long
    JOB_BATCH_SIZE: int = 5
    JOB_MAX_ATTEMPTS: int = 5  # then the job is dead-lettered (status "dead")
    JOB_RETRY_BASE_SECONDS: float = 30.0  # 30s, 1m, 2m, 4m ... between attempts
    JOB_RETRY_MAX_SECONDS: float = 3600.0

    # Email (app/email). EMAIL_BACKEND: smtp (real emails), test_mailbox (stored in the database and
    # readable at GET /api/v1/test-mailbox, for the test server), console (only logged).
    # Unset = smtp in production, test_mailbox on staging, console everywhere else.
    EMAIL_BACKEND: str | None = None
    EMAIL_FROM: str = "CareerLine <no-reply@careerline.local>"
    EMAIL_BRAND_NAME: str = "CareerLine"
    EMAIL_LOGO_URL: str = ""  # an https:// image; empty = the brand name as text
    SUPPORT_EMAIL: str = "support@careerline.local"  # the contact form goes here
    FRONTEND_URL: str = "http://localhost:5173"  # links in emails point to the website
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_SECURITY: str = "starttls"  # starttls (port 587), ssl (port 465) or none
    SMTP_TIMEOUT_SECONDS: float = 20.0
    # The test mailbox API asks for this in X-Test-Mailbox-Token when it is set
    TEST_MAILBOX_TOKEN: str = ""

    # Accounts (Day 6)
    VERIFY_EMAIL_TOKEN_HOURS: int = 48  # a confirmation link works this long, once
    PASSWORD_RESET_TOKEN_MINUTES: int = 60  # a reset link works this long, once
    LOGIN_MAX_FAILURES_PER_EMAIL: int = 5  # failed sign-ins per email address ...
    LOGIN_MAX_FAILURES_PER_IP: int = 20  # ... and per IP address ...
    LOGIN_WINDOW_MINUTES: int = 15  # ... within this window, then 429 until it passes
    SIGNUPS_PER_IP_PER_HOUR: int = 20

    # Question quality (Day 8, app/services/question_quality.py). The correct option is the single
    # longest and at least this many times the average wrong option: a review note / not served.
    QUESTION_LENGTH_REVIEW_RATIO: float = 1.3
    QUESTION_LENGTH_BLOCK_RATIO: float = 2.0
    # A skill can be tested only when every level has at least this many ACTIVE questions
    MIN_ACTIVE_QUESTIONS_PER_LEVEL: int = 15

    # The adaptive test (Day 9 engine, Day 10 test-taking; docs/adaptive-engine.md)
    ADAPTIVE_QUESTION_COUNT: int = 16
    ADAPTIVE_START_LEVEL: str = "JUNIOR"  # a first test; a retake starts at the level reached
    ATTEMPT_TIME_LIMIT_MINUTES: int = 30
    # A test whose time ran out is still scored when at least this many questions were answered
    ADAPTIVE_MIN_ANSWERS_FOR_RESULT: int = 8

    # Assessment config
    WEAK_THRESHOLD: int = 60

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("EMAIL_BACKEND", mode="before")
    @classmethod
    def _check_email_backend(cls, value):
        if value in (None, ""):
            return None
        value = str(value).strip().lower()
        if value not in EMAIL_BACKENDS:
            raise ValueError(f"EMAIL_BACKEND must be one of {', '.join(EMAIL_BACKENDS)}")
        return value

    @property
    def email_backend(self) -> str:
        if self.EMAIL_BACKEND:
            return self.EMAIL_BACKEND
        if self.is_production:
            return "smtp"
        if self.APP_ENV == "staging":
            return "test_mailbox"
        return "console"

    @property
    def test_mailbox_enabled(self) -> bool:
        """The test mailbox API: never in production, and only while emails go to it."""
        return not self.is_production and self.email_backend == "test_mailbox"

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
