"""Day 14: the beginner path, part 2. Programmes are real: Incubate and partner courses come
from seeds/programmes.json, each linked to the job roles and skills it prepares for. Clicks are
recorded (for referral reporting) and every career path and result points at a programme."""

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db.seed import load
from tests.integration.conftest import assert_error_envelope, take_test

API = settings.API_PREFIX
CATALOGUE = (
    "skills",
    "subskills",
    "job_titles",
    "job_roles",
    "job_role_skills",
    "programmes",
    "programme_roles",
    "programme_skills",
)


@pytest.fixture
def catalogue(database):
    with database.begin() as conn:
        load(conn, tables=CATALOGUE)


async def test_the_programme_list_is_real_and_public(client, catalogue):
    response = await client.get(f"{API}/programmes")
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    page = response.json()["data"]
    assert page["total"] >= 8 and page["limit"] == 20 and page["offset"] == 0
    first = page["items"][0]
    assert set(first) == {
        "programme_id",
        "name",
        "provider",
        "provider_type",
        "mode",
        "duration_weeks",
        "price",
    }
    assert first["price"]["currency"] == "NGN"


async def test_programmes_filter_by_role_and_page(client, catalogue):
    backend = (await client.get(f"{API}/programmes", params={"role_id": 102})).json()["data"]
    assert {p["programme_id"] for p in backend["items"]} == {302, 303}
    page = (await client.get(f"{API}/programmes", params={"limit": 2, "offset": 1})).json()["data"]
    assert len(page["items"]) == 2 and page["offset"] == 1
    everyone = (await client.get(f"{API}/programmes", params={"limit": 100})).json()["data"]
    assert [p["programme_id"] for p in everyone["items"]][1:3] == [
        p["programme_id"] for p in page["items"]
    ]


async def test_every_pilot_role_has_a_programme(client, catalogue):
    for role_id in range(101, 109):
        page = (await client.get(f"{API}/programmes", params={"role_id": role_id})).json()["data"]
        assert page["total"] >= 1, role_id


async def test_a_bad_page_size_is_a_validation_error(client, catalogue):
    response = await client.get(f"{API}/programmes", params={"limit": 0})
    assert_error_envelope(response, 422, "validation_error")


async def test_programme_detail(client, catalogue):
    response = await client.get(f"{API}/programmes/301")
    assert response.status_code == 200, response.text
    programme = response.json()["data"]
    assert programme["name"] == "Frontend Engineering Bootcamp"
    assert programme["price"] == {"amount": 25_000_000, "currency": "NGN"}
    assert programme["role_ids"] == [101]
    assert programme["skills"] == ["Frontend Web Development", "Version Control (Git)"]
    assert programme["url"].startswith("https://")


async def test_an_unknown_or_retired_programme_is_a_404(client, catalogue, database):
    assert_error_envelope(await client.get(f"{API}/programmes/999"), 404, "not_found")
    with database.begin() as conn:
        conn.execute(text("UPDATE programmes SET is_active = false WHERE programme_id = 303"))
    assert_error_envelope(await client.get(f"{API}/programmes/303"), 404, "not_found")
    backend = (await client.get(f"{API}/programmes", params={"role_id": 102})).json()["data"]
    assert {p["programme_id"] for p in backend["items"]} == {302}


async def test_a_click_is_recorded_and_carries_the_referral(client, catalogue, learner, db):
    response = await client.post(
        f"{API}/programmes/301/clicks",
        headers=learner["headers"],
        json={"source": "programme_list"},
    )
    assert response.status_code == 201, response.text
    click = response.json()["data"]
    assert click["programme_id"] == 301 and click["clicked_at"]
    assert click["click_id"].startswith("clk_")
    assert click["redirect_url"] == (
        f"https://example.com/programmes/frontend-engineering?ref=careerline"
        f"&click={click['click_id']}"
    )
    row = db.execute(
        text("SELECT learner_id, source, result_id FROM programme_clicks WHERE click_id = :c"),
        {"c": click["click_id"]},
    ).one()
    assert row == (learner["learner_id"], "programme_list", None)


async def test_a_click_from_a_result_must_be_your_own_result(
    client, catalogue, learner, other_learner, skill
):
    finished = await take_test(client, learner["headers"], skill)
    result_id = finished["attempt_id"]
    mine = await client.post(
        f"{API}/programmes/302/clicks",
        headers=learner["headers"],
        json={"source": "result", "result_id": result_id},
    )
    assert mine.status_code == 201, mine.text
    theirs = await client.post(
        f"{API}/programmes/302/clicks",
        headers=other_learner["headers"],
        json={"source": "result", "result_id": result_id},
    )
    assert_error_envelope(theirs, 404, "not_found")


async def test_a_click_needs_a_login_and_a_real_programme(client, catalogue, learner):
    response = await client.post(f"{API}/programmes/301/clicks", json={"source": "result"})
    assert_error_envelope(response, 401, "unauthenticated")
    response = await client.post(
        f"{API}/programmes/999/clicks", headers=learner["headers"], json={"source": "result"}
    )
    assert_error_envelope(response, 404, "not_found")
    response = await client.post(
        f"{API}/programmes/301/clicks", headers=learner["headers"], json={"source": "email"}
    )
    assert_error_envelope(response, 422, "validation_error")


async def test_seed_programmes_load_twice_and_follow_the_file(database):
    with database.begin() as conn:
        load(conn, tables=CATALOGUE)
        conn.execute(text("INSERT INTO programme_roles (programme_id, role_id) VALUES (301, 108)"))
        conn.execute(text("UPDATE programmes SET name = 'Changed' WHERE programme_id = 301"))
    with database.begin() as conn:
        counts = load(conn, tables=CATALOGUE)
        assert counts["programmes"].updated == 1
        roles = conn.execute(
            text("SELECT role_id FROM programme_roles WHERE programme_id = 301")
        ).scalars()
        assert list(roles) == [101]
        name = conn.execute(text("SELECT name FROM programmes WHERE programme_id = 301")).scalar()
        assert name == "Frontend Engineering Bootcamp"
