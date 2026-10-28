"""Day 8: job roles and the job-title ladder are real (no X-Sample-Data)."""

import pytest

from app.core.config import settings
from app.db.seed import load

API = settings.API_PREFIX


@pytest.fixture
def seeded(database):
    with database.begin() as conn:
        load(conn)


async def test_the_role_catalogue_lists_the_eight_pilot_roles(client, seeded):
    response = await client.get(f"{API}/roles", params={"limit": 20})
    assert response.status_code == 200, response.text
    assert "X-Sample-Data" not in response.headers
    page = response.json()["data"]
    assert page["total"] == 8 and page["limit"] == 20 and page["offset"] == 0
    first = page["items"][0]
    assert set(first) == {"role_id", "title", "slug", "track", "summary"}
    assert first["role_id"] == 101 and first["title"] == "Frontend Developer"
    second_page = (await client.get(f"{API}/roles", params={"limit": 3, "offset": 6})).json()
    assert [r["role_id"] for r in second_page["data"]["items"]] == [107, 108]


async def test_a_role_lists_its_skills_main_skill_first(client, seeded):
    role = (await client.get(f"{API}/roles/101")).json()["data"]
    assert role["slug"] == "frontend-developer" and role["track"] == "tech"
    assert [s["skill_id"] for s in role["skills"]] == [1, 8, 13]
    assert role["skills"][0] == {
        "skill_id": 1,
        "skill_name": "Frontend Web Development",
        "target_level": "MID",
    }
    # test ids: 200 + skill id, for the skills that can be tested now (UI/UX Design cannot)
    assert 201 in role["test_ids"] and 213 not in role["test_ids"]


async def test_an_unknown_role_is_a_404(client, seeded):
    response = await client.get(f"{API}/roles/999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_the_job_title_ladder(client, seeded):
    response = await client.get(f"{API}/job-titles")
    assert response.status_code == 200, response.text
    ladder = response.json()["data"]["items"]
    assert [(t["slug"], t["expected_level"]) for t in ladder] == [
        ("intern", "BEGINNER"),
        ("junior", "JUNIOR"),
        ("mid", "MID"),
        ("senior", "ADVANCED"),
        ("lead", "ADVANCED"),
    ]
    assert set(ladder[0]) == {"title_id", "slug", "name", "rank", "expected_level", "description"}
