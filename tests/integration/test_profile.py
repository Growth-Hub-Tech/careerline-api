"""Day 28: the profile is real (GET/PATCH /profile), so no sample route is left.

One profile per person, empty until they fill it in. visibility is the person's
share_profile_with_recruiters consent (GET /privacy/consents): changing one changes the other,
and every change is kept. completeness is the share of the profile filled in.
"""

from sqlalchemy import text

from app.core.config import settings
from tests.integration.conftest import assert_error_envelope

API = settings.API_PREFIX


async def get_profile(client, learner) -> dict:
    response = await client.get(f"{API}/profile", headers=learner["headers"])
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    return response.json()["data"]


async def patch(client, learner, **changes):
    return await client.patch(f"{API}/profile", headers=learner["headers"], json=changes)


async def test_a_new_profile_is_empty_and_private(client, learner):
    profile = await get_profile(client, learner)
    assert profile["learner_id"] == learner["learner_id"]
    assert profile["full_name"] == "Ada Learner"
    for field in ("headline", "location", "current_role", "years_experience", "weekly_hours"):
        assert profile[field] is None
    assert profile["goals"] == [] and profile["budget"] is None and profile["linkedin_url"] is None
    assert profile["visibility"] == "private"
    assert profile["completeness"] == 11  # the name only: 1 of 9


async def test_patch_changes_only_what_is_sent_and_null_clears(client, learner):
    response = await patch(
        client,
        learner,
        headline="Aspiring data analyst",
        location="Lagos",
        current_role="Customer support",
        years_experience=2,
        goals=["Get a first tech job", "  Build a portfolio  "],
        weekly_hours=10,
        budget="under_50k",
        linkedin_url="https://www.linkedin.com/in/ada-obi",
    )
    assert response.status_code == 200, response.text
    profile = response.json()["data"]
    assert profile["goals"] == ["Get a first tech job", "Build a portfolio"]
    assert profile["completeness"] == 100
    assert await get_profile(client, learner) == profile

    response = await patch(client, learner, location=None, weekly_hours=12)
    changed = response.json()["data"]
    assert changed["location"] is None and changed["weekly_hours"] == 12
    assert changed["headline"] == "Aspiring data analyst"
    assert changed["completeness"] == 89
    assert changed["updated_at"] >= profile["updated_at"]


async def test_visibility_is_the_recruiter_sharing_consent(client, db, learner):
    response = await patch(client, learner, visibility="recruiters")
    assert response.json()["data"]["visibility"] == "recruiters"
    consents = (await client.get(f"{API}/privacy/consents", headers=learner["headers"])).json()
    shared = {c["key"]: c["granted"] for c in consents["data"]["items"]}
    assert shared["share_profile_with_recruiters"] is True

    await client.put(
        f"{API}/privacy/consents",
        headers=learner["headers"],
        json={"items": [{"key": "share_profile_with_recruiters", "granted": False}]},
    )
    assert (await get_profile(client, learner))["visibility"] == "private"
    events = db.execute(
        text("SELECT count(*) FROM consent_events WHERE key = 'share_profile_with_recruiters'")
    ).scalar()
    assert events == 2


async def test_bad_values_are_refused(client, learner):
    assert_error_envelope(
        await patch(client, learner, linkedin_url="https://evil.example/in/ada"), 400, "bad_request"
    )
    assert_error_envelope(await patch(client, learner, goals=["x"] * 11), 422, "validation_error")
    assert_error_envelope(await patch(client, learner, goals=[""]), 422, "validation_error")
    assert_error_envelope(
        await patch(client, learner, weekly_hours="lots"), 422, "validation_error"
    )
    assert_error_envelope(
        await patch(client, learner, visibility="everyone"), 422, "validation_error"
    )


async def test_the_profile_needs_a_login(client):
    assert_error_envelope(await client.get(f"{API}/profile"), 401, "unauthenticated")


async def test_no_sample_route_is_left(client):
    from app.main import app

    paths = app.openapi()["paths"]
    assert not [p for p, ops in paths.items() for o in ops.values() if o.get("x-sample")]
    response = await client.get(f"{API}/profile", headers={"X-Mock-Scenario": "not_found"})
    assert response.status_code == 401  # the header means nothing now
