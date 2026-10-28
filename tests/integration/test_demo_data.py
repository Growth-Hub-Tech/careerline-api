"""Day 7: demo accounts and a demo company for the test server (python -m app.db.demo).

Loaded on start when DEMO_DATA_ON_START=true, never in production, safe to run on every
deploy. The demo company has the id of the sample organisation (41), so the sample organisation
routes answer for it."""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db import demo
from app.sample.routes.organisations import ORG_ID
from app.db.seed import load as load_seeds
from tests.integration.conftest import login

API = settings.API_PREFIX


async def test_the_demo_data_loads_twice_without_changes(db, database):
    first = await demo.load()
    second = await demo.load()
    assert first["accounts_created"] == len(demo.DEMO_ACCOUNTS)
    assert second["accounts_created"] == 0
    assert db.execute(text("SELECT count(*) FROM organisations")).scalar() == 1
    assert db.execute(text("SELECT id, name FROM organisations")).one() == (
        ORG_ID,
        demo.DEMO_COMPANY,
    )
    roles = dict(
        db.execute(
            text(
                "SELECT l.email, m.role FROM organisation_members m "
                "JOIN learner l ON l.learner_id = m.learner_id"
            )
        ).all()
    )
    assert sorted(roles.values()) == ["admin", "owner", "recruiter"]


async def test_every_demo_account_signs_in_with_the_documented_password(client):
    await demo.load()
    for account in demo.DEMO_ACCOUNTS:
        response = await login(client, account.email, demo.DEMO_PASSWORD)
        assert response.status_code == 200, (account.email, response.text)
        me = await client.get(
            f"{API}/accounts/me",
            headers={"Authorization": f"Bearer {response.json()['access_token']}"},
        )
        data = me.json()["data"]
        assert data["email_verified"] is True
        assert data["organisation_role"] == account.role
        if account.role:
            assert data["organisation_id"] == ORG_ID


async def test_a_new_organisation_after_the_demo_one_gets_a_fresh_id(db):
    await demo.load()
    new_id = db.execute(
        text("INSERT INTO organisations (name) VALUES ('Next') RETURNING id")
    ).scalar()
    assert new_id > ORG_ID


async def test_the_demo_data_is_never_loaded_in_production(monkeypatch, db):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    with pytest.raises(demo.DemoDataRefused):
        await demo.load()
    assert db.execute(text("SELECT count(*) FROM organisations")).scalar() == 0


def test_the_start_script_loads_the_demo_data_only_when_asked():
    script = (demo.REPO_ROOT / "scripts" / "start.sh").read_text()
    assert 'if [ "${DEMO_DATA_ON_START:-false}" = "true" ]' in script
    assert "python -m app.db.demo" in script


async def test_the_demo_professional_has_results_and_a_skill_history(client, database, db):
    with database.begin() as conn:
        load_seeds(conn)
    first = await demo.load()
    second = await demo.load()
    assert first["results_created"] >= 3 and second["results_created"] == 0

    token = (await login(client, demo.DEMO_PROFESSIONAL, demo.DEMO_PASSWORD)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    skills = (await client.get(f"{API}/profile/skills", headers=headers)).json()["data"]["skills"]
    assert len(skills) >= 2
    history = (await client.get(f"{API}/profile/skills/history", headers=headers)).json()["data"]
    entries = history["entries"]
    assert len(entries) == first["results_created"]
    # a retake shows progress on the same skill
    frontend = [e for e in entries if e["skill_id"] == 1]
    assert len(frontend) == 2 and frontend[0]["score"] > frontend[1]["score"]
    attempts = db.execute(
        text(
            "SELECT attempt_status, count(*) FROM test_attempt a JOIN learner l USING (learner_id) "
            "WHERE l.email = :email GROUP BY attempt_status"
        ),
        {"email": demo.DEMO_PROFESSIONAL},
    ).all()
    assert attempts == [("COMPLETED", first["results_created"])]
    one = await client.get(f"{API}/attempts/{entries[0]['attempt_id']}", headers=headers)
    assert one.json()["data"]["attempt"]["result"]["answered"] == 16


async def test_without_the_question_bank_the_demo_has_no_results(db):
    result = await demo.load()
    assert result["results_created"] == 0
