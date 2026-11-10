"""Day 29: launch hardening. In production the API refuses to start with a setting that is
unsafe or still a test one (it lists them all), and starting payments is rate limited."""

import pytest

from app.core.config import Settings
from app.core.launch_checks import production_problems

GOOD = {
    "DATABASE_URL": "postgresql://careerline:pw@db.internal:5432/careerline",
    "SECRET_KEY": "k" * 48,
    "APP_ENV": "production",
    "FRONTEND_URL": "https://careerline.ng",
    "CORS_ORIGINS": "https://careerline.ng,https://www.careerline.ng",
    "PAYSTACK_SECRET_KEY": "sk_live_" + "x" * 40,
    "EMAIL_BACKEND": "smtp",
    "SMTP_HOST": "smtp.example.com",
    "EMAIL_FROM": "CareerLine <hello@careerline.ng>",
    "CHECK_MIGRATIONS_ON_STARTUP": "true",  # the test run switches it off in the environment
    "SENTRY_DSN": "https://public@o1.ingest.sentry.io/1",
}


def settings_with(**changes) -> Settings:
    values = {**GOOD, **changes}
    return Settings(_env_file=None, **{k: v for k, v in values.items() if v is not None})


def test_good_production_settings_have_no_problems():
    assert production_problems(settings_with()) == []


@pytest.mark.parametrize(
    "changes,word",
    [
        ({"SECRET_KEY": "short"}, "SECRET_KEY"),
        ({"SECRET_KEY": "change-me" * 6}, "SECRET_KEY"),
        ({"FRONTEND_URL": "http://careerline.ng"}, "FRONTEND_URL"),
        ({"CORS_ORIGINS": "*"}, "CORS_ORIGINS"),
        ({"CORS_ORIGINS": "http://localhost:5173"}, "CORS_ORIGINS"),
        ({"PAYSTACK_SECRET_KEY": ""}, "PAYSTACK_SECRET_KEY"),
        ({"PAYSTACK_SECRET_KEY": "sk_test_abc"}, "PAYSTACK_SECRET_KEY"),
        ({"EMAIL_BACKEND": "console"}, "EMAIL_BACKEND"),
        ({"SMTP_HOST": ""}, "SMTP_HOST"),
        ({"EMAIL_FROM": "CareerLine <no-reply@careerline.local>"}, "EMAIL_FROM"),
        ({"CHECK_MIGRATIONS_ON_STARTUP": "false"}, "CHECK_MIGRATIONS_ON_STARTUP"),
        ({"SENTRY_DSN": ""}, "SENTRY_DSN"),
    ],
)
def test_each_unsafe_production_setting_is_named(changes, word):
    problems = production_problems(settings_with(**changes))
    assert len(problems) == 1 and word in problems[0], problems


def test_every_problem_is_listed_at_once():
    problems = production_problems(settings_with(SECRET_KEY="short", PAYSTACK_SECRET_KEY=""))
    assert len(problems) == 2


def test_outside_production_nothing_is_checked():
    assert production_problems(settings_with(APP_ENV="staging", SECRET_KEY="short")) == []


async def test_production_refuses_to_start_with_problems(monkeypatch):
    from app import main

    monkeypatch.setattr(main, "settings", settings_with(SECRET_KEY="short"))
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        async with main.lifespan(main.app):
            pass
