"""render.yaml: the test server and production, each web + worker + Postgres, migrations on deploy,
and no secret values in the file."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = yaml.safe_load((ROOT / "render.yaml").read_text())
SECRETS = {
    "DATABASE_URL",
    "SECRET_KEY",
    "OPENAI_API_KEY",
    "CORS_ORIGINS",
    "PAYSTACK_SECRET_KEY",
    "SMTP_PASSWORD",
    "SENTRY_DSN",
    "TEST_MAILBOX_TOKEN",
}

# (web, worker, database) per environment
ENVIRONMENTS = {
    "staging": ("careerline-api", "careerline-worker", "careerline-test-db"),
    "production": (
        "careerline-api-production",
        "careerline-worker-production",
        "careerline-production-db",
    ),
}


def _service(name: str) -> dict:
    (service,) = [s for s in BLUEPRINT["services"] if s["name"] == name]
    return service


def _env(name: str) -> dict[str, dict]:
    return {var["key"]: var for var in _service(name)["envVars"]}


def test_every_service_and_database_is_one_of_the_two_environments():
    names = {name for env in ENVIRONMENTS.values() for name in env}
    assert {s["name"] for s in BLUEPRINT["services"]} | {
        d["name"] for d in BLUEPRINT["databases"]
    } == names


@pytest.mark.parametrize("web,worker,database", ENVIRONMENTS.values())
def test_each_environment_has_a_postgres_16_database(web, worker, database):
    (db,) = [d for d in BLUEPRINT["databases"] if d["name"] == database]
    assert str(db["postgresMajorVersion"]) == "16"
    assert _service(web)["type"] == "web" and _service(worker)["type"] == "worker"


@pytest.mark.parametrize("web,worker,database", ENVIRONMENTS.values())
def test_the_web_service_migrates_before_it_starts(web, worker, database):
    service = _service(web)
    assert service["startCommand"] == "bash scripts/start.sh"
    start = (ROOT / "scripts/start.sh").read_text()
    assert start.index("alembic upgrade head") < start.index("exec uvicorn")
    assert service["healthCheckPath"] == "/healthz"


@pytest.mark.parametrize("web,worker,database", ENVIRONMENTS.values())
def test_the_worker_runs_the_worker_entry_point(web, worker, database):
    assert _service(worker)["startCommand"] == "python -m app.worker"


@pytest.mark.parametrize("web,worker,database", ENVIRONMENTS.values())
def test_both_services_use_their_own_database_and_one_secret_key(web, worker, database):
    web_env, worker_env = _env(web), _env(worker)
    assert web_env["DATABASE_URL"]["fromDatabase"]["name"] == database
    assert worker_env["DATABASE_URL"]["fromDatabase"]["name"] == database
    assert web_env["SECRET_KEY"]["generateValue"] is True
    assert worker_env["SECRET_KEY"]["fromService"]["name"] == web
    assert worker_env["SECRET_KEY"]["fromService"]["envVarKey"] == "SECRET_KEY"


@pytest.mark.parametrize("web,worker,database", ENVIRONMENTS.values())
def test_the_worker_can_charge_subscription_renewals(web, worker, database):
    assert _env(worker)["PAYSTACK_SECRET_KEY"]["sync"] is False


def test_no_secret_value_is_written_in_the_file():
    for service in BLUEPRINT["services"]:
        for key, var in _env(service["name"]).items():
            if key in SECRETS:
                assert "value" not in var, (
                    f"{service['name']}: {key} must not have a value in render.yaml"
                )


def test_the_test_server_is_not_production_and_reads_cors_from_the_dashboard():
    web = _env("careerline-api")
    assert _service("careerline-api")["branch"] == "dev"
    assert "SAMPLE_API_ENABLED" not in web  # no sample API since Day 28
    assert web["APP_ENV"]["value"] != "production"
    assert web["CORS_ORIGINS"]["sync"] is False


def test_the_test_server_loads_the_seed_files_on_every_deploy():
    start = (ROOT / "scripts/start.sh").read_text()
    assert "python -m app.db.seed" in start
    assert (
        start.index("alembic upgrade head")
        < start.index("app.db.seed")
        < start.index("exec uvicorn")
    )
    assert _env("careerline-api")["SEED_ON_START"]["value"] == "true"


def test_production_deploys_main_with_production_settings():
    web, worker, _ = ENVIRONMENTS["production"]
    for name in (web, worker):
        assert _service(name)["branch"] == "main"
        env = _env(name)
        assert env["APP_ENV"]["value"] == "production"
        assert "DEMO_DATA_ON_START" not in env
        assert "TEST_MAILBOX_TOKEN" not in env
    web_env = _env(web)
    assert web_env["SEED_ON_START"]["value"] == "false"
    assert web_env["RUN_JOBS_IN_WEB"]["value"] == "false"


def test_production_asks_for_its_real_settings_in_the_dashboard():
    web = _env(ENVIRONMENTS["production"][0])
    for key in (
        "PAYSTACK_SECRET_KEY",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_SECURITY",
        "EMAIL_FROM",
        "CORS_ORIGINS",
        "FRONTEND_URL",
        "SENTRY_DSN",
    ):
        assert web[key]["sync"] is False, key
