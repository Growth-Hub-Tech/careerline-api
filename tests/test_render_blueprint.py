"""render.yaml: web + worker + Postgres, migrations on deploy, and no secret values in the file."""

from pathlib import Path

import yaml

BLUEPRINT = yaml.safe_load((Path(__file__).resolve().parents[1] / "render.yaml").read_text())
SECRETS = {"DATABASE_URL", "SECRET_KEY", "OPENAI_API_KEY", "CORS_ORIGINS"}


def _service(kind: str) -> dict:
    (service,) = [s for s in BLUEPRINT["services"] if s["type"] == kind]
    return service


def _env(service: dict) -> dict[str, dict]:
    return {var["key"]: var for var in service["envVars"]}


def test_there_is_a_web_service_a_worker_and_a_postgres_16_database():
    (database,) = BLUEPRINT["databases"]
    assert str(database["postgresMajorVersion"]) == "16"
    assert _service("web") and _service("worker")


def test_the_web_service_migrates_before_it_starts():
    web = _service("web")
    assert web["startCommand"] == "bash scripts/start.sh"
    start = (Path(__file__).resolve().parents[1] / "scripts/start.sh").read_text()
    assert start.index("alembic upgrade head") < start.index("exec uvicorn")
    assert web["healthCheckPath"] == "/healthz"


def test_the_worker_runs_the_worker_entry_point():
    assert _service("worker")["startCommand"] == "python -m app.worker"


def test_both_services_use_the_blueprint_database_and_one_secret_key():
    web, worker = _env(_service("web")), _env(_service("worker"))
    database = BLUEPRINT["databases"][0]["name"]
    assert web["DATABASE_URL"]["fromDatabase"]["name"] == database
    assert worker["DATABASE_URL"]["fromDatabase"]["name"] == database
    assert web["SECRET_KEY"]["generateValue"] is True
    assert worker["SECRET_KEY"]["fromService"]["envVarKey"] == "SECRET_KEY"


def test_no_secret_value_is_written_in_the_file():
    for service in BLUEPRINT["services"]:
        for key, var in _env(service).items():
            if key in SECRETS:
                assert "value" not in var, (
                    f"{service['name']}: {key} must not have a value in render.yaml"
                )


def test_the_test_server_serves_the_sample_api_and_reads_cors_from_the_dashboard():
    web = _env(_service("web"))
    assert web["SAMPLE_API_ENABLED"]["value"] == "true"
    assert web["APP_ENV"]["value"] != "production"
    assert web["CORS_ORIGINS"]["sync"] is False


def test_the_test_server_loads_the_seed_files_on_every_deploy():
    start = (Path(__file__).resolve().parents[1] / "scripts/start.sh").read_text()
    assert "python -m app.db.seed" in start
    assert (
        start.index("alembic upgrade head")
        < start.index("app.db.seed")
        < start.index("exec uvicorn")
    )
    assert _env(_service("web"))["SEED_ON_START"]["value"] == "true"
