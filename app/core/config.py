from typing import Annotated, Literal

from pydantic import Field, field_validator
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
    # Connections each process may open (2 web workers and the job worker share Render's small
    # Postgres connection limit). At least 1: SQLAlchemy reads a pool size of 0 as "no limit".
    DB_POOL_SIZE: int = Field(default=5, ge=1)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0)

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_TIMEOUT_SECONDS: float = 30.0
    # Day 11: the model that explains test answers (asked once per question, then kept)
    OPENAI_EXPLANATION_MODEL: str = "gpt-4o-mini"

    # App
    APP_NAME: str = "CareerLine API"
    APP_ENV: str = "development"
    API_PREFIX: str = "/api/v1"  # Global prefix for every API route (health checks sit outside it)

    # Logging: JSON lines in production, readable console output in development
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    # Errors go to Sentry when set (the project's DSN); required in production
    SENTRY_DSN: str = ""

    # Comma-separated list of frontend origins allowed to call the API
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    # The sign-in cookie's SameSite. lax (production): the site and the API share a domain, so
    # the site's requests carry the cookie and other sites' requests do not. none: the test
    # server, whose site and API are on different domains (Safari and private windows still
    # block it there). Either way a cookie only counts on a change from one of CORS_ORIGINS.
    SESSION_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    # Refuse to start when the database is behind the latest migration
    CHECK_MIGRATIONS_ON_STARTUP: bool = True

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
    # Day 29: Paystack checkouts (credit packs and plans) one person may start per hour
    CHECKOUTS_PER_HOUR: int = 20

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

    # Organisation audits (Day 22): how long the team's test invitations work
    AUDIT_INVITATION_DAYS: int = 14
    # Day 31: an audit can be re-tested this many days after its last test was started
    RETEST_COOLDOWN_DAYS: int = 14
    # Day 31: a recruiter's shortlist (the organisation's candidates) holds this many people
    RECRUITER_SHORTLIST_LIMIT: int = 25

    # PDF skill reports (Day 12): how long a download link works
    REPORT_LINK_MINUTES: int = 15

    # Payments (Day 16): Paystack. The secret key comes only from the environment (sk_test_...
    # on the test server); without it checkout and the webhook answer 503 and nothing is charged.
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_BASE_URL: str = "https://api.paystack.co"
    PAYSTACK_TIMEOUT_SECONDS: float = 15.0
    # A checkout nobody paid is marked abandoned after this long (when it is next looked at)
    PAYMENT_ABANDON_MINUTES: int = 60
    # Day 25: a plan whose period ended without a payment stays usable (past_due) this long
    SUBSCRIPTION_GRACE_DAYS: int = 3
    # Day 26: how many times a renewal charges the saved card (once a day) before it gives up
    SUBSCRIPTION_RENEW_ATTEMPTS: int = 3

    # Privacy (Day 18): a copy of my data is kept this many days; each download link works this
    # many minutes; a deletion waits this many days so it can be cancelled
    DATA_EXPORT_DAYS: int = 7
    DATA_EXPORT_LINK_MINUTES: int = 15
    ACCOUNT_DELETION_GRACE_DAYS: int = 30

    # Assessment config
    WEAK_THRESHOLD: int = 60

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
    def async_database_url(self) -> str:
        return _with_driver(self.DATABASE_URL, "postgresql+asyncpg")

    @property
    def sync_database_url(self) -> str:
        return _with_driver(self.DATABASE_URL, "postgresql")


settings = Settings()  # required values (DATABASE_URL, SECRET_KEY) come from the environment
