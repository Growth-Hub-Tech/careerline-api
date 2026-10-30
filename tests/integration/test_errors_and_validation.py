import app.api.routes.attempts as attempts_routes
from app.core.config import settings
from tests.integration.conftest import (
    answer,
    assert_error_envelope,
    register,
)

API = settings.API_PREFIX


async def test_the_retired_declared_level_is_ignored_whatever_it_says(client, learner, skill):
    response = await client.post(
        f"{API}/attempts/start",
        headers=learner["headers"],
        json={"skill_id": skill["skill_id"], "declared_level": "WIZARD"},
    )

    assert response.status_code == 200, response.text
    assert "declared_level" not in response.json()["data"]


async def test_missing_attempt_is_404(client, learner):
    response = await client.get(f"{API}/attempts/999999", headers=learner["headers"])

    assert_error_envelope(response, 404, "not_found")


async def test_answer_for_a_missing_attempt_is_404(client, learner):
    response = await answer(client, learner["headers"], 999999, 1, 1)

    assert_error_envelope(response, 404, "not_found")


async def test_unknown_route_uses_the_error_envelope(client):
    response = await client.get(f"{API}/does-not-exist")

    assert_error_envelope(response, 404, "not_found")


async def test_body_validation_errors_use_the_envelope_and_never_echo_input(client):
    response = await client.post(
        f"{API}/auth/register", json={"email": "x@example.com", "password": 12345678901}
    )

    error = assert_error_envelope(response, 422, "validation_error")
    failed_fields = {tuple(detail["loc"]) for detail in error["details"]}
    assert ("body", "full_name") in failed_fields
    assert ("body", "password") in failed_fields
    assert "12345678901" not in response.text


async def test_unexpected_crash_is_a_generic_500_without_internals(
    client, learner, skill, monkeypatch
):
    # Old bug (fixed by the restructure): 500s used to send the exception text to the client
    internal = "asyncpg error in /srv/app/secret_module.py: SELECT hashed_password FROM learner"

    async def crash(**kwargs):
        raise RuntimeError(internal)

    monkeypatch.setattr(attempts_routes, "start_attempt", crash)
    response = await client.post(
        f"{API}/attempts/start",
        headers=learner["headers"],
        json={"skill_id": skill["skill_id"], "declared_level": "JUNIOR"},
    )

    error = assert_error_envelope(response, 500, "internal_error")
    assert error["message"] == "Something went wrong. Please try again later."
    assert "secret_module" not in response.text
    assert "SELECT" not in response.text


async def test_a_failed_save_is_not_reported_as_success(client, database):
    # Make the database refuse this learner at COMMIT time (a deferred trigger), the way a
    # dropped connection or a constraint checked at commit would.
    with database.begin() as conn:
        conn.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION refuse_on_commit() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'simulated commit failure'; END $$"
        )
        conn.exec_driver_sql("DROP TRIGGER IF EXISTS refuse_on_commit ON learner")
        conn.exec_driver_sql(
            "CREATE CONSTRAINT TRIGGER refuse_on_commit AFTER INSERT ON learner "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "WHEN (NEW.email = 'lost@example.com') EXECUTE FUNCTION refuse_on_commit()"
        )
    try:
        response = await register(client, "lost@example.com")

        with database.connect() as conn:
            saved = conn.exec_driver_sql(
                "SELECT count(*) FROM learner WHERE email = 'lost@example.com'"
            ).scalar_one()
        assert saved == 0
        # Nothing was saved, so the client must not be told it worked
        assert_error_envelope(response, 500, "internal_error")
    finally:
        with database.begin() as conn:
            conn.exec_driver_sql("DROP TRIGGER refuse_on_commit ON learner")
            conn.exec_driver_sql("DROP FUNCTION refuse_on_commit()")


async def test_start_attempt_for_an_unknown_skill_is_404(client, learner, skill):
    response = await client.post(
        f"{API}/attempts/start",
        headers=learner["headers"],
        json={"skill_id": skill["skill_id"] + 1000, "declared_level": "JUNIOR"},
    )

    error = assert_error_envelope(response, 404, "not_found")
    assert error["message"] == f"Skill {skill['skill_id'] + 1000} not found"
