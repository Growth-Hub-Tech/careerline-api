"""Settings that must be right before real people use the API (Day 29).

In production (APP_ENV=production) the API refuses to start while any of these is wrong, and
says which: a guessable signing key, a website or CORS origin that is not https, a Paystack test
key (or none: no payments), emails that would not really go out, the placeholder sender, the
schema check switched off, or no Sentry DSN (nobody would hear about errors). Elsewhere nothing
is checked.

    python -m app.core.launch_checks   # the same check from a shell (exit 1 with problems)
"""

import sys
from urllib.parse import urlsplit

from app.core.config import Settings

PLACEHOLDER_WORDS = ("change-me", "changeme", "secret-key", "your-secret", "test-secret")


def _https(url: str) -> bool:
    parts = urlsplit(url.strip())
    return parts.scheme == "https" and bool(parts.hostname) and parts.hostname != "localhost"


def production_problems(settings: Settings) -> list[str]:
    if not settings.is_production:
        return []
    problems = []
    key = settings.SECRET_KEY
    if len(key) < 32 or any(word in key.lower() for word in PLACEHOLDER_WORDS):
        problems.append("SECRET_KEY must be a random value of at least 32 characters")
    if not _https(settings.FRONTEND_URL):
        problems.append("FRONTEND_URL must be the website's https address (links in emails)")
    origins = settings.CORS_ORIGINS
    if not origins or any(origin == "*" or not _https(origin) for origin in origins):
        problems.append("CORS_ORIGINS must list the website's https origins (no * or localhost)")
    if not settings.PAYSTACK_SECRET_KEY.startswith("sk_live_"):
        problems.append(
            "PAYSTACK_SECRET_KEY must be Paystack's live secret key (sk_live_...): without it "
            "nobody can pay, and a test key takes no real money"
        )
    if settings.email_backend != "smtp":
        problems.append("EMAIL_BACKEND must be smtp (or unset) so emails really go out")
    elif not settings.SMTP_HOST:
        problems.append("SMTP_HOST must be set so emails really go out")
    if "careerline.local" in settings.EMAIL_FROM:
        problems.append("EMAIL_FROM must be a real sender address, not the placeholder")
    if not settings.CHECK_MIGRATIONS_ON_STARTUP:
        problems.append("CHECK_MIGRATIONS_ON_STARTUP must stay true (never serve an old schema)")
    if not settings.SENTRY_DSN:
        problems.append("SENTRY_DSN must be set so the team hears about errors (Sentry)")
    return problems


def main() -> int:
    from app.core.config import settings

    problems = production_problems(settings)
    for problem in problems:
        print(f"- {problem}")
    if not problems:
        print("ok" if settings.is_production else f"not production (APP_ENV={settings.APP_ENV})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
