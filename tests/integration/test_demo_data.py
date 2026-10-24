"""Day 7: demo accounts and a demo company for the test server (python -m app.db.demo).

Loaded on start when DEMO_DATA_ON_START=true, never in production, safe to run on every
deploy. The demo company has the id of the sample organisation (41), so the sample organisation
routes answer for it."""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db import demo
from app.sample.routes.organisations import ORG_ID
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
